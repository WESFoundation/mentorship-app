# 🛠️ Git Commands Cheat Sheet

Quick reference for diff inspection, selective file checkout, force pushing, and resetting local branches.

---

## 🔍 1. Inspection & Diffs

| Command | Description |
| :--- | :--- |
| `git fetch` | Download latest remote commits without merging |
| `git status` | Check working tree state & branch divergence |
| `git log main..origin/main --oneline` | List remote commits missing in local |
| `git diff main origin/main` | Show line-by-line diff between local & remote |
| `git diff --name-status main origin/main` | List changed files (`M`: Modified, `D`: Deleted) |

---

## 🎯 2. Selective File Checkout

Pull specific files from remote without merging the whole branch:

```bash
git checkout origin/main -- <file_path_1> <file_path_2>
```

---

## 💾 3. Commit & Force Push

Overwrite remote GitHub branch with current local state:

```bash
git add .
git commit -m "Commit message"
git push origin main --force
```

---

## 🔄 4. Hard Reset Local to Remote (For Teammates)

Discard all local changes and match remote GitHub 100%:

```bash
git fetch origin
git reset --hard origin/main
git clean -fd  # Remove untracked files & folders
```
