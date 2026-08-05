# -*- coding: utf-8 -*-
import io
p = r"C:\Users\santh\AppData\Local\Temp\namma_pitch\gen.py"
s = io.open(p, encoding="utf-8").read()
old = 'shape(8, {"command":"add","parent":"/slide[8]","type":"table","props":{'
new = 'cmds.append({"command":"add","parent":"/slide[8]","type":"table","props":{'
assert old in s, "pattern not found"
s = s.replace(old, new)
io.open(p, "w", encoding="utf-8").write(s)
print("patched OK")
