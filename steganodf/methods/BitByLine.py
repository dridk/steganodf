import pandas as pd
import hashlib
import hmac
import reedsolo
from typing import Callable, List


def encode(df: pd.DataFrame, message: str, hash_f: str, password = None) -> pd.DataFrame:
    encodedf = encode_df(df, message, hash_f, password)
    return encodedf

def decode(df: pd.DataFrame, hash_f: str, password = None) -> str:
    message = decode_df(df, hash_f, password)
    return message


def creat_hash_function(hash_f: str, password=None) -> Callable:
    if password == None:
        hash_function = lambda x: hashlib.new(hash_f, x.encode()).hexdigest()

    else:
        hash_function = lambda x: hmac.new(password, x.encode(), hash_f).hexdigest()
    return hash_function


def encode_index(df: pd.DataFrame, payload: bytearray, hash_function) -> List[int]:
    """ Retourne l'ordre des indices des lignes pour cacher le message
    """
#   Crée une copie du DataFrame.
    df_copy = df.copy()
    
#   Représente chaque ligne par 0 ou 1
    df_copy["bin"] = df_copy.astype(str).sum(axis=1).apply(hash_function).apply(lambda x: int(x, 16) % 2)
    
#   Crée un dictionnaire, dico = {(symbole: liste d'indice des lignes représentées par ce symbole)}.
    dico = {True: df_copy.loc[df_copy["bin"]==1].index, False: df_copy.loc[df_copy["bin"]==0].index}

    df_copy.drop("bin", axis="columns")
    
    iterables = {False: iter(dico[False]), True: iter(dico[True])}
    
#   Crée la liste ordonnée des indices des lignes qui encode le message.
    # index_list = [next(iterables[bool(1<<pos & char)]) for char in payload for pos in range(7, -1, -1)].
    index_list = []

    for char in payload:
        for pos in range(7, -1, -1):
            
#           True s'il y a un 1 à la position pos de la forme binaire de char, sinon False.
            boolean = bool(1<<pos & char)

            index_list.append(next(iterables[boolean]))
        
    return index_list


def encode_df(df: pd.DataFrame, message: str, hash_f: str, password=None) -> pd.DataFrame:
    """ Retourne le DataFrame stéganographié
    """

#   Vérifie que password soit bien un bytes ou un bytearray
    if password != None and not isinstance(password, bytes) and not isinstance(password, bytearray):
        raise TypeError("password doit être un bytes ou un bytearray.")
        
#   Crée une copie du DataFrame.
    df_copy = df.copy()
    
#   Crée une fonction de hachage
    hash_function = creat_hash_function(hash_f)
    
#   Ajoute le caractère '\n' pour indiquer la fin du message.
    message += '\n'
    index_list = []

#   Utilise un code correcteur d'erreur (Reed Solomon).
    for nb_correction_character in range(len(df)//8, 1, -1):
        try:
            rsc = reedsolo.RSCodec(nb_correction_character)
            
#           Crée un bytearray contenant le message et un code correcteur d'erreur (de longueur nb_correction_character).
            payload = rsc.encode(message.encode())
    
#           Détermine l'ordre des indicees des lignes pour cacher la payload.
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


def decode_df(df: pd.DataFrame, hash_f: str, password=None) -> str:
    """ Retourne le message caché dans le DataFrame
    """
#   Vérifie que password soit bien un bytes ou un bytearray
    if password != None and not isinstance(password, bytes) and not isinstance(password, bytearray):
        raise TypeError("password doit être un bytes ou un bytearray.")

#   Crée une copie du DataFrame.
    df_copy = df.copy()
    
#   Crée une fonction de hachage
    hash_function = creat_hash_function(hash_f)

#   Représente chaque ligne par 0 ou 1
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
