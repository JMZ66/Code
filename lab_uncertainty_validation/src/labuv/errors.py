"""User-facing calculation errors. Row and column are 1-based when set."""


class LabError(Exception):
    def __init__(self, message, *, row=None, column=None, code=None):
        super().__init__(message)
        self.row = row
        self.column = column
        self.code = code

    def located(self) -> str:
        place = []
        if self.row is not None:
            place.append(f"第{self.row}行")
        if self.column is not None:
            place.append(f"列“{self.column}”")
        prefix = ("，".join(place) + "：") if place else ""
        return prefix + str(self)
