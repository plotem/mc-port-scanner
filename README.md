## MC server port scanner

This is a discord bot I wrote to allow you to submit an IP address and a range to scan for open ports. Open Ports are then scanned to see if they are hosting minecraft servers. Written with the purpose to learn more about TCP fundamentals and how port scanners (like NMAP) work and how clients receive information from the server.

**JAVA EDITION ONLY**

Feel free to modify to your use case!

Potential usage:
- Checking if a server is online: Can use the test command to check whether a minecraft server is online from discord without opening Minecraft.
- Finding a lost port (especially if you run multiple servers on your machine)
- Exposing vulnerable ports: Scanning your own public IP shows which servers are reachable from outside.
- Checking port forwarding / troubleshooting: If people are struggling to connect to the server, they can run the bot to see if the Minecraft server is exposed to the internet. (assuming bot and server are on different networks)
- Simply learning about basic port + protocol operation and how data is encoded / decoded to exchange data between client (Minecraft Java edition in this case) and server (any exposed Minecraft server). Have fun! 

## Disclaimer

This tool is intended for **legitimate administration, testing, and educational
purposes only**, such as locating and auditing Minecraft servers on hosts that
you own or have explicit permission to scan.

**Do not use this software to scan systems you do not own or have authorization
to test.** Unauthorized port scanning (especially on mass scale) may violate your ISP's terms of service,
the terms of the network or hosting provider being scanned, and computer misuse
laws in your jurisdiction as it could be seen as some sort of attempt at a DOS attack.

By using this software, you agree that:

- You are solely responsible for how you use it and for any consequences
  that result.
- You will only scan hosts and networks you are authorized to scan.
- You will comply with all applicable laws and the policies of any network
  you interact with.

This software is provided "as is", without warranty of any kind, express or
implied. The author (me) accepts no liability for any damage, data loss, service
disruption, bans, legal action, or other harm arising from the use or misuse
of this software.

This project is not affiliated with, endorsed by, or associated with Mojang
Studios, Microsoft, or Discord.




## Setup


Requires discord python dependency:
```
pip install discord.py
```
- Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
- Reset the token and save it somewhere safe.
- Give the app relevant permissions. (Read and write messages)
- Invite the bot to your server.

Now take the token you stored to set it.
The bot reads the toekn from 'DISCORD_TOKEN' environment variable.

**Linux / macOS**
```bash
export DISCORD_TOKEN="your_token_here"
python3 mc_scanner_bot.py
```

**Windows (PowerShell)**
```powershell
$env:DISCORD_TOKEN="your_token_here"
python mc_scanner_bot.py
```

**Windows (Command Prompt)**
```
set DISCORD_TOKEN=your_token_here
python mc_scanner_bot.py
```

## Usage

Either / or ! can be used as prefix for the command.
There are two main commands, test and work. Stop can be used to halt them.

Test(check a singular IP + port combo):
```
!test <ip adress to scan> <single port to test>
```

Work (Check a singular IP + a range of ports):

```
!work <lower port bound> <upper port bound> <IP address>
```

Stop(halt any scan being currently ran):
```
!stop
```
