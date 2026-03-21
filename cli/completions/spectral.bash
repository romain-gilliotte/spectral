_spectral_apps() {
    local apps_dir="${SPECTRAL_HOME:-$HOME/.local/share/spectral}/apps"
    [[ -d "$apps_dir" ]] && COMPREPLY=($(compgen -W "$(command ls "$apps_dir" 2>/dev/null)" -- "$cur"))
}

_spectral() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local prev="${COMP_WORDS[COMP_CWORD-1]}"
    local cword=$COMP_CWORD

    # Determine group and subcommand from word positions
    local cmd1="${COMP_WORDS[1]:-}"
    local cmd2="${COMP_WORDS[2]:-}"

    # Top-level
    if [[ $cword -eq 1 ]]; then
        COMPREPLY=($(compgen -W "android auth capture community completion config extension graphql mcp openapi --help --version" -- "$cur"))
        return
    fi

    case "$cmd1" in
        community)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "install login logout publish search --help" -- "$cur"))
                return
            fi
            case "$cmd2" in
                publish) [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "--help" -- "$cur")) || _spectral_apps ;;
                search) COMPREPLY=($(compgen -W "--help" -- "$cur")) ;;
                install) COMPREPLY=($(compgen -W "--help" -- "$cur")) ;;
            esac ;;
        auth)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "analyze extract login logout refresh set --help" -- "$cur"))
                return
            fi
            case "$cmd2" in
                analyze|extract|login)
                    [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "--debug --help" -- "$cur")) || _spectral_apps ;;
                logout|refresh)
                    [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "--help" -- "$cur")) || _spectral_apps ;;
                set)
                    [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "-H --header -c --cookie -b --body-param --help" -- "$cur")) || _spectral_apps ;;
            esac ;;
        capture)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "discover inspect list proxy show --help" -- "$cur"))
                return
            fi
            case "$cmd2" in
                show) _spectral_apps ;;
                inspect) [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "--trace --help" -- "$cur")) || _spectral_apps ;;
                proxy) [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "-a --app -p --port -d --domain -e --exclude --wireguard --wg --autodetect-app --help" -- "$cur")) ;;
                discover) COMPREPLY=($(compgen -W "-p --port --wireguard --wg --help" -- "$cur")) ;;
            esac ;;
        config)
            COMPREPLY=($(compgen -W "--help" -- "$cur")) ;;
        mcp)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "analyze install migrate stdio --help" -- "$cur"))
                return
            fi
            case "$cmd2" in
                analyze) [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "--debug --skip-enrich --help" -- "$cur")) || _spectral_apps ;;
                install) COMPREPLY=($(compgen -W "--target --help" -- "$cur")) ;;
            esac ;;
        openapi)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "analyze --help" -- "$cur"))
                return
            fi
            case "$cmd2" in
                analyze) [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "-o --output --debug --skip-enrich --help" -- "$cur")) || _spectral_apps ;;
            esac ;;
        graphql)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "analyze --help" -- "$cur"))
                return
            fi
            case "$cmd2" in
                analyze) [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W "-o --output --debug --skip-enrich --help" -- "$cur")) || _spectral_apps ;;
            esac ;;
        extension)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "install listen --help" -- "$cur"))
                return
            fi
            case "$cmd2" in
                install) COMPREPLY=($(compgen -W "--extension-id --browser --help" -- "$cur")) ;;
            esac ;;
        android)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "install list patch pull replace uninstall --help" -- "$cur"))
                return
            fi
            case "$cmd2" in
                pull|patch) COMPREPLY=($(compgen -W "-o --output --help" -- "$cur")) ;;
                replace|uninstall) COMPREPLY=($(compgen -W "--help" -- "$cur")) ;;
            esac ;;
        completion)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "bash zsh" -- "$cur"))
            fi ;;
    esac
}

complete -o default -F _spectral spectral
