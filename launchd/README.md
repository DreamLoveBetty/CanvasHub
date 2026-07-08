# Main server launchd

The tracked plist is a template because launchd needs absolute paths.

Install or refresh the main server LaunchAgent from the current project checkout:

```bash
./launchd/install-server-launchd.sh
```

Optional environment overrides:

```bash
TG_MINI_APP_PYTHON=/absolute/path/to/python ./launchd/install-server-launchd.sh
TG_MINI_APP_LAUNCHD_LABEL=com.example.img-gen.server ./launchd/install-server-launchd.sh
```

The script writes a local generated plist, copies it to `~/Library/LaunchAgents/`,
and restarts the configured service.
