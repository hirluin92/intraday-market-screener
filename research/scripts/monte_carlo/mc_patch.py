import pathlib
src = pathlib.Path('/tmp/mc_v4.py').read_text()
src = src.replace(
    "BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
    "BASE = '/tmp'"
)
src = src.replace(
    "D1_PATH = os.path.join(BASE, \"datasets\", \"val_1h_production.csv\")",
    "D1_PATH = '/tmp/val_1h_production.csv'"
)
src = src.replace(
    "D5_PATH = os.path.join(BASE, \"datasets\", \"val_5m_v2.csv\")",
    "D5_PATH = '/tmp/val_5m_v2.csv'"
)
pathlib.Path('/tmp/mc_v4_fixed.py').write_text(src)
print('patched OK')
