# claude-code-status

A status line for Claude Code. It sits under the prompt and shows the
directory, subscription usage (or the cost, with an API key), context, model,
memory, git state, the agent or worktree when there is one, and the
logged-in account.

The line fits the terminal. When the window gets too narrow, fields move to
a second line first. Only when two lines aren't enough does it start dropping
detail, and then whole fields. Usage and context are never dropped. See details in
[Narrow terminals](#narrow-terminals).

**With icons**, the default.

![The status line with Nerd Font icons](docs/statusline-icons.png)

**Minimal**, plain text. Set `STATUSLINE_ICONS=0` to get it, as
[Icons or minimal](#icons-or-minimal) explains.

![The same line as plain text](docs/statusline-plain.png)

## Fields

| Field | Example | Shows |
|---|---|---|
| Directory | `~/…/my-project` | Where the session works |
| 5-hour limit | `5h 23.5% [19:45]` | Share used, and when it resets |
| Weekly limit | `7d 41.2% [Thu 14:00]` | Share used, and when it resets |
| Cost | `$1.23` | What the session has cost, with an API key only |
| Context | `477k/1M 48%` | How full the context window is |
| Model | `Opus 5.5 (high)` | Model and effort level |
| Memory | `7.6GB/14.8GB` | System RAM in use, as `free -h` counts it |
| Git | `my-project:main !2 +1 ?1 ⇡2` | Repository, branch and changes |
| Agent | `agent reviewer worktree my-feature` | The `--agent` name and the worktree, only when there is one |
| Account | `me@example.com` | Which account is logged in |

Percentages and memory turn yellow at 60% and red at 85%. From 85% they
also get a `⚠`, so the warning shows without colour too.

The git symbols follow the same format as Starship and Powerlevel10k, and remain hidden when their count is zero.

| Symbol | Means | Colour |
|---|---|---|
| `=` | Conflicted | Red |
| `!` | Modified | Yellow |
| `+` | Staged | Green |
| `?` | Untracked | Blue |
| `✘` | Deleted | Red |
| `$` | Stashed | Dim |
| `⇡` | To push | Cyan |
| `⇣` | To pull | Magenta |

A detached HEAD shows as `@a1b2c3d`. During a rebase, merge, cherry-pick,
revert or bisect, the operation follows the branch in yellow, as in
`my-project:feature|REBASE 2/5 =1`. Inside a linked worktree the name is
still the main repository's.

## Icons or minimal

Each field starts with a Nerd Font icon by default. Turn `icons` off and the
line becomes plain text with almost no labels. A token count, a GB figure, a
branch and an email are easy to tell apart without one. The two quotas are
the exception. Two bare percentages side by side would look the same, so
they keep the short labels `5h` and `7d`.

## Design choices

- **Nothing is fetched.** Everything comes from the JSON Claude Code passes
  in, one local `git status` and a few files under `.git`, Claude Code's
  account file and the OS memory figures. There's no daemon, cache or network call, and a render takes
  about 40 ms.
- **Missing means hidden.** An unknown value is left out instead of being
  shown as `0%`.
- **Usage stays on screen.** Quota, cost and context are never dropped on a
  narrow terminal.
- **Reset times are clock times.** A countdown goes stale between refreshes,
  and `19:45` doesn't.
- **Cost only when it's a bill.** Claude Code prices every session at API
  rates. With an API key that is what you pay, so it shows. On a
  subscription it would be an estimate, so it's left out. A session without
  the 5-hour and weekly limits counts as an API key, and the cost shows from
  its first cent.

## Privacy

The script stores nothing and sends nothing. It reads four things:

- The JSON Claude Code passes it. It uses the directory, model, effort,
  agent, worktree, limits, cost and context size, and never the transcript.
- One read-only `git status`. It never takes the index lock and gives up
  after 0.5 s. A few files under `.git` are also read, to spot a rebase or
  merge and count stashes.
- `.claude.json`, and only the account email in it. The login token is kept
  in a different file, which is never opened.
- The system memory totals, from `/proc/meminfo` or `vm_stat`.

It uses only Python's standard library. The directory, repository, agent
and email do show on screen, so turn off `show_cwd`, `show_git`, `show_agent`
and `show_account` before sharing your screen. `STATUSLINE_ACCOUNT=0` hides
the email without editing the script.

## Install

It runs on Linux and macOS, both tested in CI. Windows isn't supported.

You need Claude Code v2.1.153 or later and Python 3.8 or later. `git` is
only needed for the git field. The icons need a [Nerd Font](https://www.nerdfonts.com),
and without one you'll want the minimal line.

```sh
git clone https://github.com/joaotav/claude-code-status.git ~/claude-code-status
cd ~/claude-code-status
python3 scripts/make-fixtures.py > /dev/null && ./statusline.py < fixtures/full.json
```

The last line renders a sample so you can check it works. Then add this to
`~/.claude/settings.json`, with the full path to the script:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/home/you/claude-code-status/statusline.py",
    "padding": 0,
    "refreshInterval": 60
  }
}
```

For the minimal line, put `STATUSLINE_ICONS=0 ` in front of the command.
To hide the account, put `STATUSLINE_ACCOUNT=0 ` there too. That leaves the
script untouched, so `git pull` keeps working.

`refreshInterval` keeps the numbers current while you're idle. If you use
several accounts through `CLAUDE_CONFIG_DIR`, each config folder has its own
`settings.json`, and each one needs the block. To update, run `git pull`.

## Configuration

Edit `CONFIG` at the top of `statusline.py`.

| Key | Default | Effect |
|---|---|---|
| `show_cwd`, `show_quota`, `show_cost`, `show_context`, `show_model`, `show_memory`, `show_git`, `show_agent`, `show_account` | `True` | Each field |
| `icons` | `True` | Nerd Font icons. `False` gives the minimal line, and so does `STATUSLINE_ICONS=0` |
| `colour` | `True` | Colour. Setting `NO_COLOR` also turns it off |
| `warn_at`, `crit_at` | `60`, `85` | Percentages that turn yellow and red |
| `separator` | `" • "` | Goes between fields, drawn dim |
| `max_lines` | `2` | `2` wraps, `1` drops. See [Narrow terminals](#narrow-terminals) |
| `git_timeout` | `0.5` | Seconds before a slow `git status` is abandoned |

`show_input_tokens`, `show_cache_split`, `show_output_tokens`,
`show_duration` and `show_lines_changed` also exist, and are off by default.

Three environment variables work without editing the file. Put them in front
of the `statusLine` command:

| Variable | Effect |
|---|---|
| `STATUSLINE_ICONS=0` | The minimal line, as `icons: False` |
| `STATUSLINE_ACCOUNT=0` | No account email, as `show_account: False` |
| `NO_COLOR=1` | No colour, as `colour: False` |

## Narrow terminals

There are two ways to handle a narrow window, and one is chosen with
`max_lines`.

| Mode | `max_lines` | On a narrow terminal | Choose it when |
|---|---|---|---|
| Wrap, the default | `2` | Fields move to a second line, in order. Nothing is lost until both lines are full | You want every field and can spare a row |
| Drop | `1` | Stays on one line and sheds detail, then fields | Vertical space matters more |

Once there's no room left, both modes shed in the same order. The reset
times go first, then the context percentage, the full path, the git symbols
and the effort level. After that whole fields go, starting with the account,
then agent, memory, git, model and directory. Quota, cost and context always
stay, and widening the window brings everything back.

At its narrowest the line is just the two quotas and context, or the cost and
context with an API key.

![The status line at its narrowest](docs/statusline-narrow.png)

Wrap at 88 columns:

```
~/code/claude-code-status • 5h 23.5% [14:00] • 7d 41.2% [Sun 12:00] • 16k/200k 8%
Opus 5.5 (high) • 7.8GB/14.8GB • claude-code-status:main !1 • me@example.com
```

Drop at shrinking widths:

```
126 cols  claude-code-status • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5 • 7.8GB/14.8GB • claude-code-status:main • me@example.com
 87 cols  claude-code-status • 5h 23.5% • 7d 41.2% • 16k/200k • Opus 5.5
 50 cols  5h 23.5% • 7d 41.2% • 16k/200k
```

## Development

```sh
python3 -m unittest discover -s tests -t .   # tests, Python 3.11+
./scripts/run-fixtures.sh                    # render every sample input
python3 scripts/make-screenshots.py          # README images, needs Pillow and a Nerd Font
```

The tests freeze the clock and stub git, so every run gives the same result.
Some run real git in throwaway repositories, covering worktrees, stashes and
a rebase and a merge stopped on a conflict. A few read the machine's real
memory figures. CI runs
them on Linux and macOS with Python 3.11 and 3.14.

## Not included

Per-model weekly limits and the extra-usage balance. Claude Code doesn't
pass them to status lines, and fetching them would mean reading the login
token, which this script won't do.

Subagents running in the background. Status lines get only the `--agent`
name, and the rest is in the session transcript, which this script never
reads.

## Acknowledgements

The following projects served as inspiration for this mod:

- [One Dark Triptych](https://statuslin.es/c/one-dark-triptych-071e85e2) by
  adrijshikhar, for spreading a status line over more than one line, dim
  separators, and reading memory natively on Linux and macOS.
- [Starship](https://starship.rs) and
  [Powerlevel10k](https://github.com/romkatv/powerlevel10k), for the git
  status symbols and colours.
- [claude-code-statusline](https://github.com/kcchien/claude-code-statusline)
  by kcchien, for the warning sign beside a critical value and for showing
  the agent and worktree.
- [Token Weather Usage](https://github.com/augiefra/claude-mods/tree/main/plugins/token-weather-usage)
  by augiefra, which was reviewed while deciding which fields deserve a
  place on the line.

## License

MIT. See [LICENSE](LICENSE).
