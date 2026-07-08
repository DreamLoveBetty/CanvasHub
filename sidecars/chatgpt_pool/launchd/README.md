# ChatGPT Pool launchd

The tracked plist is a template because launchd requires absolute paths.

Install or refresh the LaunchAgent from the current project checkout:

```bash
./sidecars/chatgpt_pool/launchd/install-chatgpt-pool-launchd.sh
```

The script writes a local generated plist, copies it to `~/Library/LaunchAgents/`,
and restarts `com.local.tg-mini-app-img-gen.chatgpt-pool`.
