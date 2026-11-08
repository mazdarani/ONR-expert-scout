"""Start a participant session and save its files automatically."""
from expert_scout.session import run_session

if __name__ == '__main__':
    try:
        run_session()
    except (KeyboardInterrupt, EOFError):
        print('\nSession cancelled.')
