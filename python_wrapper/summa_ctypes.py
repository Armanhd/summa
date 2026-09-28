import ctypes
from pathlib import Path


NAME_WIDTH = 64
MESSAGE_LEN = 2048


class SummaModel:

    def __init__(self, library_path, config_path):

        self.library_path = str(Path(library_path).resolve())
        self.config_path = str(Path(config_path).resolve())

        self.lib = ctypes.CDLL(self.library_path)

        self.lib.summa_py_init.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_int,
        ]
        self.lib.summa_py_init.restype = ctypes.c_int

        self.lib.summa_py_evaluate.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_int,
        ]
        self.lib.summa_py_evaluate.restype = ctypes.c_int

        message = ctypes.create_string_buffer(MESSAGE_LEN)

        status = self.lib.summa_py_init(
            self.config_path.encode(),
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                "SUMMA initialization failed: "
                + message.value.decode(errors="replace")
            )


    def evaluate(self, parameters):

        names = list(parameters.keys())
        values = [float(parameters[name]) for name in names]

        nparam = len(names)

        blob = b""

        for name in names:

            encoded = name.encode()

            if len(encoded) >= NAME_WIDTH:
                raise ValueError(
                    "Parameter name exceeds NAME_WIDTH: " + name
                )

            blob += encoded.ljust(NAME_WIDTH, b"\0")

        name_buffer = ctypes.create_string_buffer(
            blob,
            len(blob),
        )

        value_array = (ctypes.c_double * nparam)(*values)

        objective = ctypes.c_double()
        message = ctypes.create_string_buffer(MESSAGE_LEN)

        status = self.lib.summa_py_evaluate(
            nparam,
            name_buffer,
            NAME_WIDTH,
            value_array,
            ctypes.byref(objective),
            message,
            MESSAGE_LEN,
        )

        if status != 0:
            raise RuntimeError(
                "SUMMA evaluation failed: "
                + message.value.decode(errors="replace")
            )

        return objective.value