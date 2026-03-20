import sys
import requests
import click
from ..constants import ADMIN_API_PORT

@click.group()
def cli():
    """Owlet Admin CLI"""
    pass

@cli.command()
@click.argument('channel')
@click.argument('code')
def approve(channel, code):
    """Approve a pairing request."""
    url = f"http://127.0.0.1:{ADMIN_API_PORT}/approve/{channel}/{code}"
    try:
        response = requests.post(url)
        if response.status_code == 200:
            try:
                result = response.json()
                click.echo(f"✅ Approved! User {result['user_id']} ({channel}) is now authorized.")
            except ValueError:
                click.echo(f"✅ Approved! (But failed to parse response: {response.text})")
        else:
            try:
                detail = response.json().get('detail', 'Unknown error')
                click.echo(f"❌ Failed: {detail}")
            except ValueError:
                click.echo(f"❌ Failed: Status {response.status_code}, Response: {response.text}")

    except requests.exceptions.ConnectionError:
        click.echo("Error: Could not connect to Gateway Admin API. Is the gateway running?")

def main():
    cli()

if __name__ == "__main__":
    main()
