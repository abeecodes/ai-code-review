import ast


def parse_literal(text):
    return ast.literal_eval(text)
