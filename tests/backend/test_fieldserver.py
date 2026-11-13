"""Small pure pieces of the field-test launcher."""

from backend.fieldserver import lan_ip, parse_env


def test_parse_env_handles_comments_quotes_and_blank_values():
    env = parse_env('''
# a comment
POSTGRES_USER=turnwise
POSTGRES_PORT=5433   # host port
QUOTED="has # inside"
EMPTY=
URL=postgresql+asyncpg://u:p@127.0.0.1:5433/db
not a setting
''')
    assert env == {"POSTGRES_USER": "turnwise", "POSTGRES_PORT": "5433", "QUOTED": "has # inside",
                   "EMPTY": "", "URL": "postgresql+asyncpg://u:p@127.0.0.1:5433/db"}


def test_lan_ip_looks_like_an_ipv4_address():
    parts = lan_ip().split(".")
    assert len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
