# stuff

*put it somewhere*

<img src="stuff.svg" alt="stuff" width="420pt">

## use

- upload: `sftp upload@stuff.problem.li`, put into `upload/` — key auth only. Bookmarks: [stuff.duck](stuff.duck) (Cyberduck), [stuff.filezilla.xml](stuff.filezilla.xml) (FileZilla → File → Import)
- describe: say what `foo.zip` is in a `foo.zip.txt` sidecar. Undescribed stuff lives a week, described stuff a year — then info@ gets a mail with one-click keep/delete (and a describe form for the undescribed). The sidecar travels with its file everywhere.
- download: `https://stuff.problem.li/<filename>` — no listing, you need the exact name
- expiry: no reaction to the mail → 30 days later the file moves to `deleted/`, a year after that it is gone. Keep, describe and re-upload all reset the clock.

## deploy

```bash
gh repo clone blemli/stuff
cd stuff
kamal setup   # first time only, afterwards: kamal deploy
```

Secrets come from 1password (`op signin`), see `.kamal/secrets`. DNS: `stuff.problem.li` → webhost — the same CNAME carries sftp, since kamal-proxy only owns 80/443 and port 22 goes straight to the accessory.

## architecture

- one file, no JS, and no upload code at all: sshd does the uploads (atmoz/sftp as kamal accessory), flask only serves
- the filesystem is the database — mtime is the expiry clock; sqlite only remembers warning tokens
- one-click keep/delete mail links, logli-style random tokens
- rate-limited + cached, lossy UDP logging to logli
- ssh host keys persist in `/opt/stuff-keys`, so the fingerprint survives redeploys
