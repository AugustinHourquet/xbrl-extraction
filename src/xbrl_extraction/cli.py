# src/xbrl_extraction/cli.py
import argparse


def main():
    parser = argparse.ArgumentParser(prog="xbrl-extract")
    parser.add_argument("filing", help="path to .xbrl or .xml file")
    parser.add_argument("--provider", default="none")
    args = parser.parse_args()
    print(f"filing: {args.filing}")  # TODO: wire to extractor


if __name__ == "__main__":
    main()
