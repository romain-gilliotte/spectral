#compdef spectral

_spectral_apps() {
    local apps_dir="${SPECTRAL_HOME:-$HOME/.local/share/spectral}/apps"
    [[ -d "$apps_dir" ]] && compadd -- "$apps_dir"/*(:t)
}

_spectral() {
    local curcontext="$curcontext" ret=1

    if (( CURRENT == 2 )); then
        local -a groups=(
            'android:Android APK tools'
            'auth:Authentication management'
            'capture:Capture management'
            'community:Community tool catalog'
            'completion:Generate shell completion script'
            'config:Configure API key and model'
            'extension:Chrome Extension integration'
            'graphql:GraphQL analysis'
            'mcp:MCP tool generation and server'
            'openapi:OpenAPI analysis'
        )
        _describe 'command group' groups && ret=0
        return ret
    fi

    case "${words[2]}" in
        community)
            if (( CURRENT == 3 )); then
                local -a subcmds=(
                    'install:Install a tool collection'
                    'login:Authenticate with GitHub'
                    'logout:Remove stored GitHub token'
                    'publish:Publish tools to the catalog'
                    'search:Search for tool collections'
                )
                _describe 'community command' subcmds && ret=0
            else
                case "${words[3]}" in
                    publish)
                        _arguments \
                            '--help[Show help]' \
                            '*:app name:_spectral_apps' && ret=0 ;;
                    search|install)
                        _arguments \
                            '--help[Show help]' && ret=0 ;;
                esac
            fi ;;
        auth)
            if (( CURRENT == 3 )); then
                local -a subcmds=(
                    'analyze:Detect auth and generate script'
                    'extract:Extract auth tokens from traces'
                    'login:Interactive auth login'
                    'logout:Remove stored token'
                    'refresh:Refresh auth token'
                    'set:Manually set auth headers/cookies'
                )
                _describe 'auth command' subcmds && ret=0
            else
                case "${words[3]}" in
                    analyze|extract|login)
                        _arguments \
                            '--debug[Save LLM prompts/responses]' \
                            '--help[Show help]' \
                            '*:app name:_spectral_apps' && ret=0 ;;
                    logout|refresh)
                        _arguments \
                            '--help[Show help]' \
                            '*:app name:_spectral_apps' && ret=0 ;;
                    set)
                        _arguments \
                            '(-H --header)'{-H,--header}'[Header as Name: Value]' \
                            '(-c --cookie)'{-c,--cookie}'[Cookie as name=value]' \
                            '(-b --body-param)'{-b,--body-param}'[Body param as key=value]' \
                            '--help[Show help]' \
                            '*:app name:_spectral_apps' && ret=0 ;;
                esac
            fi ;;
        capture)
            if (( CURRENT == 3 )); then
                local -a subcmds=(
                    'discover:Log domains without MITM'
                    'inspect:Inspect capture contents'
                    'list:List captured apps'
                    'proxy:MITM proxy capture'
                    'show:Show captures for an app'
                )
                _describe 'capture command' subcmds && ret=0
            else
                case "${words[3]}" in
                    show)
                        _arguments '*:app name:_spectral_apps' && ret=0 ;;
                    inspect)
                        _arguments \
                            '--trace[Show details for a specific trace]' \
                            '--help[Show help]' \
                            '*:app name:_spectral_apps' && ret=0 ;;
                    proxy)
                        _arguments \
                            '(-a --app)'{-a,--app}'[App name for storage]' \
                            '(-p --port)'{-p,--port}'[Proxy listen port]' \
                            '(-d --domain)'{-d,--domain}'[Domain pattern]' \
                            '(-e --exclude)'{-e,--exclude}'[Exclude domain from MITM]' \
                            '--wireguard[Use WireGuard VPN mode]' \
                            '--autodetect-app[Auto-detect foreground Android app via ADB]' \
                            '--help[Show help]' && ret=0 ;;
                    discover)
                        _arguments \
                            '(-p --port)'{-p,--port}'[Proxy listen port]' \
                            '--wireguard[Use WireGuard VPN mode]' \
                            '--help[Show help]' && ret=0 ;;
                esac
            fi ;;
        config)
            _arguments '--help[Show help]' && ret=0 ;;
        mcp)
            if (( CURRENT == 3 )); then
                local -a subcmds=(
                    'analyze:Analyze captures into MCP tools'
                    'install:Install MCP server into Claude Desktop or Claude Code'
                    'migrate:Migrate on-disk tools and app.json to current schema'
                    'stdio:Start MCP server on stdio'
                )
                _describe 'mcp command' subcmds && ret=0
            else
                case "${words[3]}" in
                    analyze)
                        _arguments \
                            '--debug[Save LLM prompts/responses]' \
                            '--skip-enrich[Skip enrichment step]' \
                            '--help[Show help]' \
                            '*:app name:_spectral_apps' && ret=0 ;;
                    install)
                        _arguments \
                            '--target[Target client (claude-desktop or claude-code)]' \
                            '--help[Show help]' && ret=0 ;;
                esac
            fi ;;
        openapi)
            if (( CURRENT == 3 )); then
                local -a subcmds=(
                    'analyze:Analyze captures into OpenAPI spec'
                )
                _describe 'openapi command' subcmds && ret=0
            else
                case "${words[3]}" in
                    analyze)
                        _arguments \
                            '(-o --output)'{-o,--output}'[Output base name]' \
                            '--debug[Save LLM prompts/responses]' \
                            '--skip-enrich[Skip enrichment step]' \
                            '--help[Show help]' \
                            '*:app name:_spectral_apps' && ret=0 ;;
                esac
            fi ;;
        graphql)
            if (( CURRENT == 3 )); then
                local -a subcmds=(
                    'analyze:Analyze captures into GraphQL schema'
                )
                _describe 'graphql command' subcmds && ret=0
            else
                case "${words[3]}" in
                    analyze)
                        _arguments \
                            '(-o --output)'{-o,--output}'[Output base name]' \
                            '--debug[Save LLM prompts/responses]' \
                            '--skip-enrich[Skip enrichment step]' \
                            '--help[Show help]' \
                            '*:app name:_spectral_apps' && ret=0 ;;
                esac
            fi ;;
        extension)
            if (( CURRENT == 3 )); then
                local -a subcmds=(
                    'install:Install native messaging host'
                    'listen:Native host (called by Chrome)'
                )
                _describe 'extension command' subcmds && ret=0
            else
                case "${words[3]}" in
                    install)
                        _arguments \
                            '--extension-id[Chrome extension ID]' \
                            '--browser[Browser to configure]' \
                            '--help[Show help]' && ret=0 ;;
                esac
            fi ;;
        android)
            if (( CURRENT == 3 )); then
                local -a subcmds=(
                    'install:Install APK'
                    'list:List packages'
                    'patch:Patch APK'
                    'pull:Pull APK'
                    'replace:Pull, patch, uninstall, and reinstall'
                    'uninstall:Uninstall package'
                )
                _describe 'android command' subcmds && ret=0
            else
                case "${words[3]}" in
                    pull|patch)
                        _arguments \
                            '(-o --output)'{-o,--output}'[Output path]' \
                            '--help[Show help]' && ret=0 ;;
                    replace|uninstall)
                        _arguments \
                            '--help[Show help]' && ret=0 ;;
                esac
            fi ;;
        completion)
            if (( CURRENT == 3 )); then
                local -a shells=(bash zsh)
                _describe 'shell' shells && ret=0
            fi ;;
    esac

    return ret
}

_spectral "$@"
