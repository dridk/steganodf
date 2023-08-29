import pandas as pd
import hashlib
import hmac
import reedsolo
from typing import List

def creat_hash_function(hash: str, password=None):
    if password == None:
        hash_function = lambda x: hashlib.new(hash, x.encode()).hexdigest()

    else:
        hash_function = lambda x: hmac.new(password, x.encode(), hash).hexdigest()
    return hash_function



def encode_index(df: pd.DataFrame, payload: bytearray, hash_function) -> List[int]:
    """ Retourne l'ordre des indices des lignes pour cacher le message
    """

#   Représente chaque ligne par 0 ou 1
    df["bin"] = df.astype(str).sum(axis=1).apply(hash_function).apply(lambda x: int(x, 16) % 2)

#   Crée un dictionnaire, dico = {(symbole: liste d'indice des lignes représentées par ce symbole)}.
    dico = {True: df.loc[df["bin"]==1].index, False: df.loc[df["bin"]==0].index}

    print(f"len(dico[True]) = {len(dico[True])}")
    print(f"len(dico[False]) = {len(dico[False])}\n")

    iterables = {False: iter(dico[False]), True: iter(dico[True])}

#   Crée la liste ordonnée des indices des lignes qui encode le message.
    # index_list = [next(iterables[bool(1<<pos & char)]) for char in payload for pos in range(7, -1, -1)].

    index_list = []

    for char in payload:
        for pos in range(7, -1, -1):
            boolean = bool(1<<pos & char)

            index_list.append(next(iterables[boolean]))

    return index_list



def encode_df(df: pd.DataFrame, message: str, hash: str, password=None) -> pd.DataFrame:
    """ Retourne le DataFrame stéganographié
    """

    if password != None and not isinstance(password, bytes) and not isinstance(password, bytearray):
        raise TypeError("password doit être un bytes ou un bytearray.")


#   Crée une copie du DataFrame.
    df_copy = df.copy()

    hash_function = creat_hash_function(hash, password)

#   Ajoute le caractère '\n' pour indiquer la fin du message.
    message += '\n'

    index_list = []

#   Utilise un code correcteur d'erreur (Reed Solomon).
    nb_correction_character = len(df)//8
    while nb_correction_character > 2:
        nb_correction_character -= 1

        try:
            rsc = reedsolo.RSCodec(nb_correction_character)
            payload = rsc.encode(message.encode())

#           Détermine l'odre des indices des lignes du DataFrame pour encoder le message.
            index_list = encode_index(df_copy, payload, hash_function)
            print(payload)
            break

        except:
            continue

    if index_list == []:
        raise Exception("Le message est trop long.")

#   Crée le DataFrame stéganographié.
    df_encode = df_copy.loc[index_list]

#   Ajoute les lignes non utilisées au DataFrame stéganographié.
    df_copy = pd.concat([df_encode,df_copy.drop(index_list)]).reset_index(drop=True)

    return df_copy



def decode_df(df: pd.DataFrame, hash: str, password=None) -> str:
    """ Retourne le message caché dans le DataFrame
    """

    if password != None and not isinstance(password, bytes) and not isinstance(password, bytearray):
        raise TypeError("password doit être un byte ou un bytearray.")

#   Crée une copie du DataFrame.
    df_copy = df.copy()

#   Crée la fonction de hachage
    hash_function = creat_hash_function(hash, password)

#   Représente chaque ligne par 0 ou 1
    df["bin"] = df.astype(str).sum(axis=1).apply(hash_function).apply(lambda x: int(x, 16) % 2)

    sequence = df["bin"]

#   Retire le dernier bloc si il ne contient pas 8 lignes, puis on inverse la liste.
    sequence = list(reversed(sequence[:len(sequence) - len(sequence)%8]))

#   Crée un liste de taille len(sequence)//8 (c-à-d le nombre de caractères que l'on peut cacher dans le DataFrame).
    list_char = [0]*(len(sequence)//8)

    char = 0

    for position in range(len(sequence)):

#       Après avoir lu 8 lignes, on passe au caractère suivant.
        if position%8 == 0 and position != 0:
            char += 1

#       Si sequence[position] == True, alors on ajoute 2 puissance 'position%8' à list_char[char].
        list_char[char] = list_char[char] | sequence[position] << position%8

    list_char = bytearray(list(reversed(list_char)))
    print(list_char)

#   Détermine la longueur du message.
    len_message = list_char.index(b'\n')+1

    payload = None

#   Utilise un code correcteur d'erreur (Reed Solomon).
    for len_payload in range(len(sequence)//8, len_message, -1):
        try:
            rsc = reedsolo.RSCodec(len_payload - len_message)
            payload = rsc.decode(list_char[:len_payload])[0][:-1].decode()
            break

        except:
            continue

#   Si le code correcteur d'erreur ne fonctionne pas, on retourne quand même le message trouvé.
    if payload == None:
        payload = list_char
        print("Il y a trop d'erreurs pour utiliser le code correcteur d'erreur.\n")

    return payload