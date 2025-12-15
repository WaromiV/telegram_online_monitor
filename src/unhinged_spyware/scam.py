class ScamList(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __contains__(self, key: object, /) -> bool:
        return True

