"""A tiny stand-in for doorman + xania's lobby, replaying the text of a real session (runs/*/Smokea.log), so the
session logic is tested without a MUD. It knows one existing player, "Oldie" with password "secret1"."""

from __future__ import annotations

import asyncio
import contextlib

IAC, DO, WILL, WONT = 255, 253, 251, 252
BANNER = "\n\r  .... NO! ...   A N I A\n\r\n\rState thy name and enter the realm of Xania: "
PROMPT_DEFAULT = "<20/20hp 100/100m 100mv 0cd> "
MOTD = "Welcome to Xania! See 'help rules' and 'help commands'.\n\r[Hit return to continue]\n\r"
ROOM = "Entrance to Mud School\n\r  This is the entrance.\n\r[Exits: north down]\n\r"
LONG = "".join(f"line {i}\n\r" for i in range(30))


class FakeMud:
    def __init__(self):
        self.received: list[str] = []
        self.server: asyncio.base_events.Server | None = None
        self.port = 0
        self.play = None  # optional: command -> output (without prompt), or None to fall through
        self.autoloot = True
        self.moves = 100  # shown in the bot prompt

    def bot_prompt(self) -> str:
        return f"<bot 20/20 100/100 {self.moves}/100 1000 0 0>\n\r"

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        if hasattr(self.server, "close_clients"):  # 3.13+: don't wait on a client a failed test left open
            self.server.close_clients()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.server.wait_closed(), 2)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        def out(text: str):
            writer.write(text.encode("latin-1"))

        async def line() -> str:
            raw = await reader.readline()
            if not raw:
                raise ConnectionError
            # drop our client's telnet replies (IAC WONT x), as doorman does
            data = bytearray(raw)
            while IAC in data:
                i = data.index(IAC)
                del data[i:i + 3]
            text = data.decode("latin-1").rstrip("\r\n")
            self.received.append(text)
            return text

        prompt = PROMPT_DEFAULT
        try:
            writer.write(bytes([IAC, DO, 24, IAC, DO, 31, IAC, WONT, 1]))
            out(BANNER)
            name = (await line()).capitalize()
            if name == "Illi":
                out("Illegal name, try another.\n\rName: ")
                await line()
                return
            if name == "Oldie":
                out("Password: ")
                writer.write(bytes([IAC, WILL, 1]))
                if await line() != "secret1":
                    out("\n\rOur survey said <Crude buzzer noise>.\n\rWrong password.\n\r")
                    return
                out("\n\r")
            else:
                out(f"Did I hear that right - '{name}' (Y/N)? ")
                if (await line()).lower() != "y":
                    out("OK, try again: ")
                    await line()
                    return
                out(f"Welcome new character, to Xania.\n\rThink of a password for {name}: ")
                await line()
                out("\n\rPlease retype password: ")
                await line()
                out("\n\rThe following races are available:\n\r Human Dwarf\n\rWhat is your race (help for more "
                    "information)? ")
                await line()
                out("Are you male, female or other (M/F/O)? ")
                await line()
                out("OK. Personal pronouns can be set later.\n\rThe following classes are available:\n\r"
                    "What is your class (help for more information)? ")
                await line()
                out("\n\rYou may be good, neutral, or evil.\n\rWhich alignment (G/N/E)? ")
                await line()
                out("\n\rCustomize (Y/N)? \n\r")
                await line()
            out("Does your terminal support ANSI colour (Y/N/Return = as saved)?")
            await line()
            out(MOTD)
            await line()
            out(ROOM + prompt)
            while True:
                cmd = await line()
                if self.play and not cmd.startswith(("prompt ", "scroll ")) and cmd != "quit":
                    reply = self.play(cmd)
                    if reply is not None:
                        out(reply + (self.bot_prompt() if prompt != PROMPT_DEFAULT else prompt))
                        continue
                if cmd.startswith("prompt "):
                    prompt = self.bot_prompt()
                    out("Ok - prompt set.\n\r" + prompt)
                elif cmd == "scroll 0":
                    out("Paging at maximum.\n\r" + prompt)
                elif cmd == "autoloot":  # new characters start with it on
                    self.autoloot = not getattr(self, "autoloot", True)
                    out(("Automatic corpse looting set." if self.autoloot else "Autolooting removed.") + "\n\r"
                        + prompt)
                elif cmd == "look":
                    out(ROOM + prompt)
                elif cmd == "long":
                    out(LONG[:120] + "[Hit Return to continue]\n\r")
                    await line()
                    out(LONG[120:] + prompt)
                elif cmd == "quit":
                    out("You quit reality for the game.\n\r")
                    return
                else:
                    out("Huh?\n\r" + prompt)
        except ConnectionError:
            pass
        finally:
            with contextlib.suppress(Exception):
                await writer.drain()
            writer.close()
