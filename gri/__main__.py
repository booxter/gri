#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import os
import sys

import click
import rich
import yaml
from click_help_colors import HelpColorsGroup
from rich import box
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.theme import Theme

from gri.console import TERMINAL_THEME
from gri.gerrit import GerritServer
from gri.review import Review

theme = Theme(
    {
        "normal": "",  # No or minor danger
        "moderate": "yellow",  # Moderate danger
        "considerable": "dark_orange",  # Considerable danger
        "high": "red",  # High danger
        "veryhigh": "dim red",  # Very high danger
        "branch": "magenta",
        "wip": "bold yellow",
    }
)
term = Console(theme=theme, highlighter=rich.highlighter.ReprHighlighter(), record=True)

LOG = logging.getLogger(__name__)


class Config(dict):
    def __init__(self):
        super().__init__()
        self.update(self.load_config("~/.gertty.yaml"))

    @staticmethod
    def load_config(config_file):
        config_file = os.path.expanduser(config_file)
        with open(config_file, "r") as stream:
            try:
                return yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                LOG.error(exc)
                sys.exit(2)


# pylint: disable=too-few-public-methods
class App:
    def __init__(self, server=None, user=None):
        self.cfg = Config()
        self.servers = []
        self.user = user
        for srv in (
            self.cfg["servers"]
            if server is None
            else [self.cfg["servers"][int(server)]]
        ):
            try:
                self.servers.append(GerritServer(url=srv["url"], name=srv["name"]))
            except SystemError as exc:
                LOG.error(exc)
        if not self.servers:
            sys.exit(1)

        self.reviews = list()
        term.print(self.header())

    def query(self, query):
        """Performs a query and stores result inside reviews attribute"""
        self.reviews = list()
        for item in self.servers:

            for record in item.query(query=query):
                self.reviews.append(Review(record, item))

    def header(self):
        srv_list = " ".join(s.name for s in self.servers)
        return f"[dim]GRI using {len(self.servers)} servers: {srv_list}[/]"

    def report(self, query=None, title="Reviews"):
        """Produce a table report based on a query."""
        if query:
            self.query(query)

        cnt = 0

        table = Table(title=title, border_style="grey15", box=box.MINIMAL)
        table.add_column("Review", justify="right")
        table.add_column("Age")
        table.add_column("Project/Subject")
        table.add_column("Meta")
        table.add_column("Score", justify="right")

        for review in sorted(self.reviews):
            table.add_row(*review.as_columns())
            # if ctx.params["abandon"] and review.score < 1:
            #     if review.age() > ctx.params["abandon_age"] and query != "incoming":
            #         review.abandon(dry=ctx.params["force"])
            LOG.debug(review.data)
            cnt += 1
        term.print(table)
        extra = f" from: [cyan]{query}[/]" if query else ""
        term.print(f"[dim]-- {cnt} changes listed{extra}[/]")


class CustomGroup(HelpColorsGroup):
    def get_command(self, ctx, cmd_name):
        """Undocumented command aliases for lazy users"""
        aliases = {
            "o": owned,
            "m": merged,
            "i": incoming,
        }
        try:
            cmd_name = aliases[cmd_name].name
        except KeyError:
            pass
        return super().get_command(ctx, cmd_name)


@click.group(
    cls=CustomGroup,
    invoke_without_command=True,
    help_headers_color="yellow",
    help_options_color="green",
    context_settings=dict(max_content_width=9999),
    chain=True,
)
@click.option(
    "--abandon",
    "-a",
    default=False,
    help="Abandon changes (delete for drafts) when they are >90 days old "
    "and with negative score. Requires -f to perform the action.",
    is_flag=True,
)
@click.option(
    "--abandon-age",
    "-z",
    default=90,
    help="default=90, number of days for which changes are subject to abandon",
)
@click.option("--user", "-u", default="self", help="Query another user than self")
@click.option(
    "--server",
    "-s",
    default=None,
    help="[0,1,2] key in list of servers, Query a single server instead of all",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Filename to dump the result in, currently only HTML is supported",
)
@click.option(
    "--force",
    "-f",
    default=False,
    help="Perform potentially destructive actions.",
    is_flag=True,
)
@click.option("--debug", "-d", default=False, help="Debug mode", is_flag=True)
@click.pass_context
# pylint: disable=unused-argument,too-many-arguments,too-many-locals
def cli(ctx, debug, server, abandon, force, abandon_age, user, output):

    handler = RichHandler(show_time=False, show_path=False)
    LOG.addHandler(handler)

    LOG.warning("Called with %s", ctx.params)
    if debug:
        LOG.setLevel(level=logging.DEBUG)

    if " " in user:
        user = f'"{user}"'

    ctx.obj = App(server=server, user=user)

    if ctx.invoked_subcommand is None:
        LOG.info("I was invoked without subcommand, assuming implicit `owned` command")
        ctx.invoke(owned)

    if output:
        term.save_html(path=output, theme=TERMINAL_THEME)


@cli.command()
@click.pass_context
def owned(ctx):
    """Changes originated from current user (implicit)"""
    query = "status:open"
    query += f" owner:{ctx.obj.user}"
    if ctx.obj.user == "self":
        title = "Own reviews"
    else:
        title = f"Reviews owned by {ctx.obj.user}"
    ctx.obj.report(query=query, title=title)


@cli.command()
@click.pass_context
def incoming(ctx):
    """Incoming reviews (not mine)"""
    query = f"reviewer:{ctx.obj.user} status:open"
    ctx.obj.report(query=query, title="Merged Reviews")


@cli.command()
@click.pass_context
@click.option(
    "--age",
    default=1,
    help="Number of days to look back, adds -age:NUM",
)
def merged(ctx, age):
    """merged in the last number of days"""
    query = f" status:merged -age:{age}d"
    query += f" owner:{ctx.obj.user}"

    ctx.obj.report(query=query, title=f"Merged Reviews ({age}d)")


if __name__ == "__main__":

    cli()  # pylint: disable=no-value-for-parameter
