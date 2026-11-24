import sys
import traceback
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

def main():
    diagnostic = next((Path(sys.argv[i + 1]) for i, flag in enumerate(sys.argv[:-1])
                       if flag in ("--smoke", "--capture", "--probe")), None)
    if diagnostic:
        diagnostic.mkdir(parents=True, exist_ok=True)

        def record_error(kind, value, trace):
            with (diagnostic / "error.txt").open("a", encoding="utf-8") as log:
                traceback.print_exception(kind, value, trace, file=log)
            sys.__excepthook__(kind, value, trace)

        sys.excepthook = record_error
    from spotiflying.app import main as start

    return start()


if __name__ == "__main__":
    raise SystemExit(main())
