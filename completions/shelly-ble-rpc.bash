_shelly_ble_rpc_methods=(
    Shelly.GetDeviceInfo
    Shelly.GetStatus
    Shelly.GetConfig
    Shelly.Reboot
    Shelly.Update
    Sys.GetConfig
    Sys.GetStatus
    Switch.GetConfig
    Switch.GetStatus
    Switch.Set
    Switch.Toggle
    Light.GetConfig
    Light.GetStatus
    Light.Set
    Light.Toggle
    Cover.GetConfig
    Cover.GetStatus
    Cover.Open
    Cover.Close
    Cover.Stop
    Cover.GoTo
    Input.GetConfig
    Input.GetStatus
    Input.SetConfig
    Script.GetConfig
    Script.GetStatus
    Script.Start
    Script.Stop
    MQTT.GetConfig
    BLE.GetConfig
    Cloud.GetConfig
    WiFi.GetConfig
)

_shelly_ble_rpc_devices() {
    local command_name="${COMP_WORDS[0]}"
    local address name rest header=1

    while IFS=$'\t' read -r address name rest; do
        if ((header)); then
            header=0
            continue
        fi
        [[ -n "$address" ]] && COMPREPLY+=("$address")
        [[ -n "$name" ]] && COMPREPLY+=("$name")
    done < <("$command_name" paired --tsv 2>/dev/null)
}

_shelly_ble_rpc_filter_completions() {
    local candidate
    local -a filtered=()
    for candidate in "${COMPREPLY[@]}"; do
        [[ "$candidate" == "$1"* ]] && filtered+=("$candidate")
    done
    COMPREPLY=("${filtered[@]}")
}

_shelly_ble_rpc_completions() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local action="${COMP_WORDS[1]}"
    local positional=0 word index expect_value=0
    local -a options

    if ((COMP_CWORD == 1)); then
        COMPREPLY=( $(compgen -W "scan paired rpc pair unpair" -- "$cur") )
        return
    fi

    case "$action" in
        scan)
            options=(-d --debug --tsv --full --force --timeout --concurrency)
            ;;
        paired)
            options=(-d --debug --tsv)
            ;;
        rpc)
            options=(-d --debug --raw --timeout)
            ;;
        pair)
            options=(-d --debug --timeout)
            ;;
        unpair)
            options=(-d --debug --timeout)
            ;;
        *)
            return
            ;;
    esac

    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "${options[*]}" -- "$cur") )
        return
    fi

    [[ "${COMP_WORDS[COMP_CWORD - 1]}" == "--raw" ||
        "${COMP_WORDS[COMP_CWORD - 1]}" == "--timeout" ]] && return

    for ((index = 2; index < COMP_CWORD; index++)); do
        word="${COMP_WORDS[index]}"
        if ((expect_value)); then
            expect_value=0
            continue
        fi
        case "$word" in
            --raw|--timeout)
                expect_value=1
                ;;
            --*)
                ;;
            *)
                ((positional++))
                ;;
        esac
    done

    case "$action:$positional" in
        rpc:0|pair:0|unpair:0)
            COMPREPLY=()
            _shelly_ble_rpc_devices
            _shelly_ble_rpc_filter_completions "$cur"
            ;;
        rpc:1)
            COMPREPLY=()
            local method
            for method in "${_shelly_ble_rpc_methods[@]}"; do
                [[ "$method" == "$cur"* ]] && COMPREPLY+=("$method")
            done
            ;;
    esac
}

complete -F _shelly_ble_rpc_completions shelly-ble-rpc
complete -F _shelly_ble_rpc_completions shelly_ble_rpc.py
