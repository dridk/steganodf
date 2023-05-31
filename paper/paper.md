---
title: 'Steganodf: Hide a watermark in your tabular data'
tags:
  - Python
  - Steganography
  - Watermark
  - Pandas
  - DataFrame
authors:
  - name: Sacha Schutz^[co-first author] # note this makes a footnote saying 'co-first author'
    orcid: 0000-0002-4563-7537
    affiliation: "1" # (Multiple affiliations must be quoted)
  - name: Nathan Foulquier ^[co-first author]
    orcid: 0000-0003-4095-8099
    affiliation: "1"

affiliations:
 - name: CHRU Brest, Centre de donnée clinique, Brest, France
   index: 1

date: 30 May 2023
bibliography: paper.bib

---


Plan : 

# Introduction 

- La steganographie est l'art de cacher un message
- bcp d'algorithme et d'outils , mais surtout pour l'images 
- Surement car dans des données textuel , la payload est trop petites 
- Il y a bien des methodes qui utilise des caractere ASCII speciaux mais c'est bof 
- On pourrait altérer les données, mais c'est bof
- Ici on a choisi de permuter les lignes block de 6, pour stocker 1 bytes

# Math et meth 

## Encodage 
- Soit un tableau T ( n x m )
- Chaque lignes est hashé avec SHA256 + HMAC 
- On ordonne par hash : Ce sera l'index de références 
- On groupe les ligne par block_size = 6 
- 6! largement suffisant pour stocker 1 bytes 
- On savegarde la payload préalablement compressé 
- On utilise l'algo X qui permet de calculer la nieme permutation 

## Decodage 
- on calcul le hash 
- On reordonne par hash 
- On calcul le differentiel et on extrait le bytes 

## Gestion des doublons  
- Les doublons sont généré en créant artificellemetn un index sur la premiere colonnes ordonnée de facon lexicographique 

## Resultats 
- on a implementer l'outil en python : steganodf 
- Taille de la payload en fonction de la taille du fichier 
- Temps de calcul en fonction de la taille du fichier 

## Discussion 
- C'est indetectable a priori ( il faut le mot de passe ) . si il a les deux fichiers, le nombre de permutation a tester est de X. 
- C'est facillement sterélisable .. Mais on peut utiliser des fichier en read only
- 




