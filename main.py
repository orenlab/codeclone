import importlib

from . import codeclone as cl

cl.__all__()
cl.main()

a = __import__(credits)

b = importlib.import_module("codeclone")
