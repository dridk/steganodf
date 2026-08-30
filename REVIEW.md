# Revue de l'algorithme steganodf

Revue de l'algorithme `BitPool` tel qu'implémenté dans `steganodf/algorithms/bitpool.py`,
de sa capacité, de son modèle de menace, et des pistes alternatives envisagées puis
écartées. Les bugs listés en fin de document ont été corrigés dans le même lot.

---

## 1. Ce que fait réellement le code

> ⚠️ `paper/paper.md` décrit un schéma différent (tri par hash, blocs de 6 lignes,
> code de Lehmer). **Ce n'est pas ce qui est implémenté.** Le papier reste un plan
> initial ; ce document décrit le code.

Les lignes ne sont jamais modifiées, seul leur **ordre** l'est.

1. **Empreinte par ligne.** Toutes les colonnes sont converties en texte et
   concaténées (`compute_hash`), puis hashées en MD5 — ou en HMAC-MD5 si un mot de
   passe est fourni. On garde les `bit_per_row` bits de **poids fort du premier octet**
   du digest. Chaque ligne porte donc un symbole dans `[0, 2^bit_per_row)`, déterminé
   par son contenu seul.
2. **Le pool.** Les indices de lignes sont rangés dans `2^bit_per_row` files FIFO,
   une par symbole (`create_pool`).
3. **Mise en paquets.** La payload alimente un flux **infini** de paquets fontaine LT
   (`steganodf/lt/`), puis chaque paquet reçoit un CRC32 et un code Reed-Solomon :

   ```
   +--------------+---------------------+-------+--------------------+
   |   HEADER LT  |        DATA         |  CRC  |     CORRECTION     |
   |    12 o      |        20 o         |  4 o  |        10 o        |
   +--------------+---------------------+-------+--------------------+
                            46 octets au total
   ```

4. **Écriture.** Chaque paquet est découpé en groupes de `bit_per_row` bits ; écrire
   le symbole `v` = sortir la prochaine ligne de la file `v` (`encode_chunk`). On
   continue à tirer des paquets fontaine **tant qu'aucune file n'est vide**, ce qui
   remplit tout le tableau de redondance. Les lignes restantes sont mélangées et
   ajoutées à la fin.
5. **Décodage aveugle.** On recalcule les symboles, puis on fait **glisser une fenêtre
   de la taille d'un paquet sur tous les offsets possibles** ; à chaque offset on tente
   un décodage Reed-Solomon, on valide par cohérence de l'en-tête et par CRC32, et on
   injecte les paquets valides dans le décodeur LT jusqu'à convergence.

---

## 2. Points forts

- **Distorsion nulle.** Aucune cellule n'est altérée. Pour de la donnée clinique ou
  scientifique, c'est le bon compromis, et ça distingue nettement l'approche des
  méthodes par LSB.
- **Canal sans mémoire.** Le symbole d'une ligne dépend de son contenu, pas de sa
  position. Une suppression ou une insertion de ligne ne fait que retirer/ajouter un
  symbole au flux : la fenêtre glissante se resynchronise d'elle-même. C'est ce qui
  donne la tolérance au *cropping*, et c'est précisément ce qu'un découpage en blocs
  de position fixe (le schéma du papier) ne sait **pas** faire.
- **Doublons gérés nativement.** Deux lignes identiques ont le même symbole et sont
  interchangeables — aucun traitement particulier n'est nécessaire. Une approche par
  rang de permutation, elle, exige des empreintes distinctes.
- **Décodage aveugle.** Le fichier original n'est pas nécessaire.
- **Pile de robustesse cohérente.** LT (effacements) + Reed-Solomon (erreurs dans un
  paquet) + CRC32 (détection) couvre bien les trois menaces accidentelles :
  altération de cellules, suppression de lignes, troncature.

---

## 3. Capacité : les chiffres

### Débits comparés

Borne supérieure absolue d'un canal par permutation de `n` lignes :
`log2(n!) / n ≈ log2(n) − 1,44` bits par ligne.

| Schéma | bits / ligne |
|---|---|
| `paper/paper.md` : 1 octet par bloc de 6 lignes | **1,33** |
| Lehmer optimal, blocs de 6 (`log2(6!)/6`) | 1,58 |
| Lehmer optimal, blocs de 20 | 3,05 |
| `BitPool` `bit_per_row=1` | 1,00 |
| `BitPool` `bit_per_row=2` | 2,00 |
| `BitPool` `bit_per_row=4` | 4,00 |
| Borne théorique, n = 10 000 | **11,85** |

### Rendement du paquet

`20 / 46 = 43 %` de la capacité brute atteint l'utilisateur. Le reste :
en-tête LT 12 o (26 %), Reed-Solomon 10 o (22 %), CRC 4 o (9 %).

En pratique, sur un DataFrame de 10 000 lignes en `bit_per_row=1` :

| | octets |
|---|---|
| capacité brute (`10000 × 1 / 8`) | 1 250 |
| après en-tête/CRC/RS (`get_max_theoretical_payload_size`) | 543 |
| marge de sécurité LT (`get_max_payload_size`) | **135** |
| borne théorique de la permutation | 14 807 |

Soit **~0,9 % de la capacité du canal**. Une bonne part de cette perte est le prix
assumé de la robustesse, mais pas toute (voir §5).

### Le code fontaine dégénère sur les petites payloads

Pour un filigrane typique (UUID, 16 octets) et `data_size = 20`, on a `K = 1` bloc
source : **tous les paquets fontaine sont identiques**, le code LT se réduit à de la
simple répétition, et on paie quand même les 12 octets d'en-tête `(filesize,
blocksize, blockseed)` dont les trois champs sont soit constants soit inutiles. Le
rendement tombe à `16/46 = 35 %`.

### Taille minimale du jeu de données

Un paquet occupe `packet_size × 8 / bit_per_row` lignes, donc avec les réglages par
défaut il faut **au moins 368 lignes** (184 en `bit_per_row=2`, 92 en `bit_per_row=4`)
— et il faut en plus que chaque valeur de hash apparaisse assez souvent. L'exemple
`iris` (150 lignes) du README ne pouvait donc **jamais** fonctionner : `encode`
renvoyait silencieusement un DataFrame simplement mélangé. Il lève désormais une
`AlgorithmError` explicite.

### Coût du décodage

`n − window` tentatives de décodage Reed-Solomon (≈ 9 600 pour 10 000 lignes), doublé
si `reverse_reading=True`, plus un `map_elements` — une UDF Python non vectorisée —
pour hasher chaque ligne. C'est le goulet d'étranglement de la bibliothèque.

---

## 4. Modèle de menace : ce que le filigrane ne protège pas

- **Un `ORDER BY` efface tout.** Trier, dédoublonner ou repartitionner le jeu de
  données détruit le filigrane, sans perte d'information et **sans avoir besoin du mot
  de passe**. C'est inhérent à tout marquage par permutation. Toute une classe de
  pipelines (Spark, `GROUP BY`, réécriture Parquet) le fait sans intention hostile.
- **Détectable si l'hôte était trié.** Si le fichier d'origine avait un ordre naturel
  (date, identifiant), la version marquée apparaît en désordre — c'est visible à l'œil
  nu, sans mot de passe. La propriété d'indétectabilité ne vaut que pour des jeux de
  données dont l'ordre est déjà sans signification.
- **Pas de résistance à la collusion.** Deux copies marquées différemment permettent,
  par comparaison des ordres, de localiser les positions porteuses d'information.
- **`password=None` par défaut.** L'empreinte est alors un MD5 public : n'importe qui
  peut lire le message *et* en réinscrire un autre. Le mot de passe devrait être
  obligatoire pour tout usage de traçabilité.
- **Le CRC32 n'est pas un MAC.** Il détecte les erreurs de transmission, pas une
  falsification. La payload n'est ni chiffrée ni authentifiée.
- **L'empreinte dépend de l'ordre des colonnes.** Réordonner, ajouter ou renommer une
  colonne efface le message aussi sûrement qu'un tri (voir §7, point ouvert).

---

## 5. Pistes évaluées

### Écartée : code de Lehmer sur blocs auto-resynchronisants

L'idée : trier les lignes par hash pour obtenir un **ordre canonique** reconstructible,
le découper en blocs, et coder dans le **rang de permutation** de chaque bloc
(`log2(k!)` bits pour `k` lignes). Le problème des blocs de position fixe est qu'une
seule suppression décale tout ce qui suit et détruit tous les blocs suivants. La
parade serait un découpage **défini par le contenu** (*content-defined chunking*, à la
rsync) : on coupe après toute ligne vérifiant `h'(ligne) mod B == 0`, si bien que la
frontière est attachée à une ligne et non à un indice — une suppression n'endommage
alors que son propre bloc.

**Écartée après calcul.** Le débit de Lehmer plafonne à `log2(k!)/k ≈ log2(k) − 1,44` :
il faut des blocs **exponentiellement grands** pour monter en débit, là où `BitPool`
donne `bit_per_row` bits par ligne avec une localité de **une** ligne. Pour égaler
`bit_per_row=4`, il faudrait des blocs de ~43 lignes. Le schéma du papier (1,33
bit/ligne) est donc dominé par ce qui est déjà implémenté à `bit_per_row=2`
(2 bits/ligne), qui est en plus plus local et gère les doublons. Le CDC n'apporterait
que la suppression de la fenêtre glissante en `O(n)` au décodage — un gain de temps de
calcul, pas de capacité.

### Implémentée : `bit_per_row` libre par flux de bits

La contrainte `bit_per_row ∈ {1, 2, 4}` ne venait que du découpage octet-par-octet
de `encode_chunk` / `decode_chunk`. Les paquets sont désormais écrits comme un
**flux de bits continu** (un groupe de `b` bits peut chevaucher deux octets) :
`b` est libre de 1 à 16 (au-delà, le pool de `2^b` files coûterait plus de
mémoire que le DataFrame lui-même, pour un gain nul en pratique).

L'implémentation a révélé un second verrou, invisible dans l'analyse théorique :
les octets **répétés d'un paquet à l'autre** (l'en-tête LT constant, et les données
elles-mêmes quand la payload est petite — le champ data ne prend que `2^K − 1`
valeurs) consomment toujours les *mêmes* files du pool, et la plus petite d'entre
elles (~`n/2^b` lignes) plafonnait le nombre de paquets à une poignée dès `b = 10`.
Chaque paquet est donc **brouillé** (XOR avec un pad dérivé de son propre
`blockseed`, seul champ variant — `scramble_block`) avant CRC et Reed-Solomon, ce
qui rend la consommation des files uniforme. Ce brouillage profite aussi aux petits
`b` (capacité réelle mesurée à `b=4` : 1 144 → 1 505 octets sur 10 000 lignes).

Capacité réelle mesurée (10 000 lignes, recherche dichotomique du plus grand
payload décodable) : 360 o à `b=1`, 1 505 o à `b=4`, **1 579 o à `b=8`** ; au-delà
(`b ≥ 10`) l'épuisement des files domine, conformément à la borne
`b ≲ log2(n) − 3`. Le plein rendement demande `b ≲ log2(n) − 4`.

### Autres pistes documentées

- **En-tête court quand `K = 1`** (implémenté). Pour un payload ≤ `data_size − 1`,
  la fontaine LT dégénère en répétition : l'en-tête de 12 octets est remplacé par
  un nonce de 2 octets (qui alimente le brouillage) plus un octet de longueur —
  paquet de 36 octets au lieu de 46, ~25 % de copies redondantes en plus mesurées,
  et un seul paquet valide reconstruit tout le message (pas de décodeur LT).
- **`AlterationAlgorithm`** (la classe est vide) : marquage par altération plutôt que
  par permutation. LSB sur colonnes numériques façon Agrawal & Kiernan (VLDB 2002,
  sélection des tuples par HMAC sur une clé primaire virtuelle), ou QIM / dither
  modulation (Chen & Wornell) pour un compromis distorsion/robustesse réglable.
  Capacité ~`n × m` bits, et surtout **survit au tri** — ce qu'aucune approche par
  permutation ne peut faire.
- **Substitution dans une classe d'équivalence** pour les colonnes catégorielles
  (format de date, unités, casse) : sans perte sémantique.
- **Marquage statistique** (Sion et al.) : décaler la moyenne de sous-ensembles
  pseudo-aléatoires d'une fraction de σ. Très robuste, faible capacité.
- **Codes anti-collusion** (Boneh–Shaw, Tardos) si l'objectif est le *fingerprinting*
  — identifier qui a fuité — plutôt que le simple marquage.

---

## 6. Bugs identifiés et corrigés

| Fichier | Problème | Statut |
|---|---|---|
| `pyproject.toml` | Aucun `[project.scripts]` : la commande `steganodf` documentée dans le README **n'existait pas** après `pip install` | corrigé |
| `pyproject.toml` | `requires-python` absent | corrigé |
| `Makefile` | `pip install -e ".[all]"` alors que l'extra s'appelle `dev` → `make install` échouait | corrigé |
| `__main__.py` | `for i, _ in SUPPORTED_FORMATS_IO` itère sur les clés → `ValueError` au moment d'afficher le message d'erreur de format | corrigé |
| `__main__.py` | Un décodage raté affichait une ligne vide et sortait en code 0 | corrigé (stderr + code 1) |
| `algorithm.py` | `Algorithm.__init__(**kwargs)` avalait silencieusement tout kwarg inconnu ; conséquence directe : les tests passaient `parity_size=0`, paramètre inexistant, donc `test_without_parity` tournait en réalité **avec** Reed-Solomon actif | corrigé (`AlgorithmError`) |
| `bitpool.py` | `int.to_bytes(n)` sans `byteorder` : ne fonctionne qu'à partir de Python 3.11 | corrigé |
| `bitpool.py` | `RSCodec(0)` instancié même avec `correction_size=0` | corrigé |
| `bitpool.py` | **Corruption silencieuse** : en cas d'échec, `bytes_dump()` concaténait les blocs LT partiellement résolus, produisant une payload décalée et corrompue présentée comme le message. C'est ce qui rendait `test_estimate_payload_size` rouge sur `main` | corrigé (`b""` + `logging.warning`) |
| `bitpool.py` | Aucun moyen de distinguer « pas de filigrane » d'un décodage réussi : `decode()` jetait le champ `success` | corrigé (`decode_details`) |
| `bitpool.py` | `get_max_payload_size` : le facteur `// 3` était trop optimiste — mesuré à **1 échec sur 25 graines**. Ramené à `// 4`, mesuré à **0 échec sur 60** (avec et sans Reed-Solomon) | corrigé |
| `bitpool.py` | Un DataFrame trop petit produisait silencieusement un tableau mélangé sans payload | corrigé (`AlgorithmError` explicite) |
| `bitpool.py` | `get_max_theoretical_payload_size` annotée `-> int` renvoyait un `float` | corrigé |
| `bitpool.py` | `random.shuffle` non seedé → encodage non reproductible | corrigé (paramètre `seed`) |
| `bitpool.py` | En-tête LT nommé `(block_count, data_size, uuid)` alors qu'il vaut `(filesize, blocksize, blockseed)` | corrigé |
| `bitpool.py` | Code mort : `find_packet` (`pass`), `valid_blocks` inutilisé, `random.shuffle` commenté | supprimé |
| `bitchunk.py` | `BitChunk` renvoyait `df` et `b"hello"`, référencé nulle part | supprimé |
| `pyscript.json` (racine) | Périmé (0.3.0 + duckdb) et non référencé — seul `www/pyscript.json` est utilisé | supprimé |
| `README.md` | L'exemple Python passait un `str` au lieu de `bytes` (`TypeError`), décodait `df` au lieu de `new_df`, et utilisait `iris` (150 lignes) alors que le minimum est de 368 lignes | corrigé |
| `tests/test_bitpool.py` | `f"...{i}"` avec `i` non défini → `NameError` au moment même où le test échoue | corrigé |

### Points ouverts

- **`compute_hash` est désormais canonique** (résolu). Les cellules sont jointes
  par `pl.concat_str` avec le séparateur `0x1F`, les nulls reçoivent un marqueur
  distinct de la chaîne vide, et les colonnes sont triées par nom
  (désactivable via `sort_columns=False`) : réordonner les colonnes ne casse
  plus le décodage. Renommer, ajouter ou supprimer une colonne le casse
  toujours. Les fichiers marqués par les versions ≤ 0.2.5 ne sont plus
  décodables (rupture de format assumée).
- **`www/pyscript.json` fige la version** (`steganodf-0.2.5-...whl`) : tout bump de
  version dans `pyproject.toml` casse le site sans que rien ne le signale.
- **Performance du décodage** : `map_elements` (UDF Python) + `O(n)` décodages
  Reed-Solomon. Non traité ici.
