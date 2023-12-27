from .algorithm import Algorithm


class PermutationAlgorithm(Algorithm):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def encode_indexes(self, indexes: list, payload: bytes) -> list:
        raise NotImplemented()


    def decode_indexes(self, indexes: list, payload: bytes) -> list: 
        raise NotImplemented()
        
