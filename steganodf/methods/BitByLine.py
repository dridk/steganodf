import pandas as pd
import hashlib
import hmac
import reedsolo
from typing import Callable, List


def encode(df: pd.DataFrame, message: str, hash_name="md5", password = None) -> pd.DataFrame:
    df_steg = encode_df(df, message, hash_name, password)
    return df_steg


def decode(df: pd.DataFrame, hash_name="md5", password = None) -> str:
    message = decode_df(df, hash_name, password)
    return message


def creat_hash_function(hash_name: str, password = None) -> Callable:
    """ Créé une fonction de hachage
    """
    if password == None:
        hash_function = lambda x: hashlib.new(hash_name, x.encode()).hexdigest()

    else:
        hash_function = lambda x: hmac.new(password, x.encode(), hash_name).hexdigest()

    return hash_function


def encode_index(df: pd.DataFrame, payload: bytearray, hash_function) -> List[int]:
    """ Retourne l'ordre des indices des lignes du DataFrame pour cacher le message
    """
#   Crée une copie du DataFrame.
    df_copy = df.copy()

#   Représente chaque ligne par 0 ou 1.
    df_copy["bin"] = df_copy.astype(str).sum(axis=1).apply(hash_function).apply(lambda x: int(x, 16) % 2)

#   Crée un dictionnaire, dico = {(symbole: liste d'indice des lignes représentées par ce symbole)}.
    dico = {True: df_copy.loc[df_copy["bin"]==1].index, False: df_copy.loc[df_copy["bin"]==0].index}

    df_copy.drop("bin", axis="columns")

    iterables = {False: iter(dico[False]), True: iter(dico[True])}

#   Crée la liste ordonnée des indices des lignes du DataFrame qui encode le message.
    # index_list = [next(iterables[bool(1<<pos & char)]) for char in payload for pos in range(7, -1, -1)].
    index_list = []

    for char in payload:
        for pos in range(7, -1, -1):

#           True s'il y a un 1 à la position pos de la forme binaire de char, sinon False.
            boolean = bool(1<<pos & char)

            index_list.append(next(iterables[boolean]))

    return index_list


def encode_df(df: pd.DataFrame, message: str, hash_name: str, password=None) -> pd.DataFrame:
    """ Retourne le DataFrame stéganographié
    """
#   Crée une copie du DataFrame.
    df_copy = df.copy()

#   Crée une fonction de hachage.
    hash_function = creat_hash_function(hash_name, password.encode())

#   Ajoute le caractère '\n' pour indiquer la fin du message.
    message += '\n'
    index_list = []

#   Utilise un code correcteur d'erreur (Reed Solomon).
    for nb_correction_character in range(len(df)//8, 1, -1):
        try:
            rsc = reedsolo.RSCodec(nb_correction_character)

#           Crée un bytearray contenant le message et un code correcteur d'erreur (de longueur nb_correction_character).
            payload = rsc.encode(message.encode())

#           Détermine l'ordre des indices des lignes du DataFrame pour cacher la payload.
            index_list = encode_index(df_copy, payload, hash_function)
            break
        except:
            continue

    if len(index_list)<1:
        raise Exception("Le message est trop long.")

#   Crée le DataFrame stéganographié.
    df_encode = df_copy.loc[index_list]

#   Ajoute les lignes non utilisées au DataFrame stéganographié.
    df_copy = pd.concat([df_encode,df_copy.drop(index_list)]).reset_index(drop=True)

    return df_copy


def decode_df(df: pd.DataFrame, hash_name: str, password=None) -> str:
    """ Retourne le message caché dans le DataFrame
    """
#   Crée une copie du DataFrame.
    df_copy = df.copy()

#   Crée une fonction de hachage.
    hash_function = creat_hash_function(hash_name, password.encode())

#   Représente chaque ligne par 0 ou 1.
    df_copy["bin"] = df_copy.astype(str).sum(axis=1).apply(hash_function).apply(lambda x: int(x, 16) % 2)
    sequence = df_copy["bin"]
    df_copy.drop("bin", axis="columns")

#   Retire le dernier bloc si il ne contient pas 8 lignes, puis on inverse la liste.
    sequence = list(reversed(sequence[:len(sequence) - len(sequence)%8]))

    list_char = [0]*(len(sequence)//8)
    char = 0

    for position in range(len(sequence)):

#       Après avoir lu 8 lignes, on passe au caractère suivant.
        if position % 8 == 0 and position != 0:
            char += 1

#       Si sequence[position] == True, alors on ajoute 2 puissance 'position%8' à list_char[char].
        list_char[char] = list_char[char] | sequence[position] << position%8

    list_char = bytearray(list(reversed(list_char)))

#   Détermine la longueur du message.
    try:
        len_message = list_char.index(b'\n')+1
    except:
        raise Exception("Erreur sur le mot de passe ou le nom de la fonction de hachage.")

    payload = None

#   Utilise un code correcteur d'erreur (Reed Solomon).
    for len_payload in range(len(sequence)//8, len_message, -1):
        try:
            rsc = reedsolo.RSCodec(len_payload - len_message)
            payload, rmesecc, errata_pos = rsc.decode(list_char[:len_payload])
            message = payload[:-1].decode()

#           Si le DataFrame a été altéré et la payload a été endommagé, alors on donne les positions des erreurs sur la payload.
            if len(errata_pos)>0:
              print(f"Nombre d'erreurs détectées: {len(errata_pos)}, leur position sur la payload: {list(errata_pos)}.\n")

              print(f"Lignes altérées qui ont endommagé la payload = {[[j*8+i for i in range(8) if bool((rmesecc[j]^list_char[j]) & 1 << (7-i))] for j in errata_pos]}.\n")
            break
        except:
            continue

#   Si le code correcteur d'erreur ne fonctionne pas, on retourne quand même le message trouvé.
    if payload == None:
        message = list_char
        print("Il y a trop d'erreurs pour utiliser le code correcteur d'erreur.\n")

    return message
