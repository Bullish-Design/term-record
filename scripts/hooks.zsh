#!/usr/bin/env zsh
# Termrecord shell hooks for zsh
# Source this in .zshrc after atuin init

typeset -g _TERMRECORD_RECORDING_ID=""
typeset -g _TERMRECORD_PENDING_FILE=""
typeset -g _TERMRECORD_CAST_FILE=""
typeset -g _TERMRECORD_START_TIME=""
typeset -g _TERMRECORD_SKIP_WRAP=""
typeset -g _TERMRECORD_ORIGINAL_CMD=""
typeset -g _TERMRECORD_STORAGE="${TERMRECORD_STORAGE:-$HOME/.local/share/termrecord}"
typeset -g _TERMRECORD_CONFIG="${TERMRECORD_CONFIG:-$HOME/.config/termrecord/config.toml}"

# Cache for dotfile lookups
typeset -gA _TERMRECORD_CACHE=()

_termrecord_enabled_for_dir() {
    local dir="$1"

    # Check cache
    (( ${+_TERMRECORD_CACHE[$dir]} )) && {
        [[ "${_TERMRECORD_CACHE[$dir]}" == "1" ]]
        return
    }

    # Walk up looking for .termrecord.toml
    local check_dir="$dir"
    while [[ "$check_dir" != "/" && -n "$check_dir" ]]; do
        if [[ -f "$check_dir/.termrecord.toml" ]]; then
            if grep -qE '^\s*enabled\s*=\s*false' "$check_dir/.termrecord.toml" 2>/dev/null; then
                _TERMRECORD_CACHE[$dir]="0"
                return 1
            else
                _TERMRECORD_CACHE[$dir]="1"
                return 0
            fi
        fi
        check_dir="${check_dir:h}"
    done

    # Check path rules via helper
    if (( $+commands[termrecord-check-path] )); then
        if termrecord-check-path "$dir" 2>/dev/null; then
            _TERMRECORD_CACHE[$dir]="1"
            return 0
        else
            _TERMRECORD_CACHE[$dir]="0"
            return 1
        fi
    fi

    _TERMRECORD_CACHE[$dir]="1"
    return 0
}

_termrecord_should_record() {
    [[ "$TERMRECORD_ENABLED" == "0" ]] && return 1
    [[ "$TERMRECORD_ENABLED" == "1" ]] && return 0
    _termrecord_enabled_for_dir "$PWD"
}

_termrecord_generate_id() {
    local timestamp_ms=$(date +%s%3N)
    local random_hex=$(head -c 4 /dev/urandom | xxd -p)
    echo "rec_${timestamp_ms}_${random_hex}"
}

_termrecord_setup_recording() {
    local cmd="$1"

    [[ -z "$cmd" ]] && return 1

    _TERMRECORD_RECORDING_ID="$(_termrecord_generate_id)"
    _TERMRECORD_START_TIME="$(date +%s.%N)"
    _TERMRECORD_ORIGINAL_CMD="$cmd"

    local date_path=$(date +%Y/%m/%d)
    local output_dir="${_TERMRECORD_STORAGE}/recordings/${date_path}"
    mkdir -p "$output_dir" 2>/dev/null || return 1

    _TERMRECORD_CAST_FILE="${output_dir}/${_TERMRECORD_RECORDING_ID}.cast"
    _TERMRECORD_PENDING_FILE="${output_dir}/${_TERMRECORD_RECORDING_ID}.pending"

    # Write pending file with original command (not wrapped)
    cat > "$_TERMRECORD_PENDING_FILE" <<EOF
{
  "id": "${_TERMRECORD_RECORDING_ID}",
  "command": $(printf '%s' "$cmd" | jq -Rs .),
  "timestamp": ${_TERMRECORD_START_TIME},
  "cwd": "${PWD}",
  "shell": "zsh",
  "user": "${USER}",
  "hostname": "${HOST}",
  "terminal": {
    "width": ${COLUMNS:-120},
    "height": ${LINES:-40},
    "term": "${TERM:-xterm-256color}"
  },
  "cast_path": "${_TERMRECORD_CAST_FILE}"
}
EOF

    return 0
}

# ZLE widget to wrap commands with asciinema rec
_termrecord_accept_line() {
    # Reset skip flag
    _TERMRECORD_SKIP_WRAP=""

    # Only process non-empty buffers when recording is enabled
    if [[ -n "$BUFFER" ]] && _termrecord_should_record; then
        # Check for shell builtins that modify state (can't be wrapped)
        case "${${(z)BUFFER}[1]}" in
            cd|pushd|popd|export|unset|source|.|eval|exec|builtin|command|alias|unalias|hash|rehash)
                # Record metadata but don't wrap - these need to run in current shell
                _termrecord_setup_recording "$BUFFER" && _TERMRECORD_SKIP_WRAP=1
                ;;
            *)
                # Set up recording and wrap the command
                if _termrecord_setup_recording "$BUFFER"; then
                    local quoted_cmd=${(q)BUFFER}
                    BUFFER="asciinema rec --quiet --overwrite -c ${quoted_cmd} ${(q)_TERMRECORD_CAST_FILE}"
                fi
                ;;
        esac
    fi

    # Call original accept-line
    zle .accept-line
}

# Install the widget
zle -N accept-line _termrecord_accept_line

_termrecord_precmd() {
    local exit_code=$?

    # Skip if no active recording
    [[ -z "$_TERMRECORD_RECORDING_ID" ]] && return $exit_code
    [[ ! -f "$_TERMRECORD_PENDING_FILE" ]] && {
        _termrecord_reset_state
        return $exit_code
    }

    # If we skipped wrapping (builtin), delete pending since no cast exists
    if [[ -n "$_TERMRECORD_SKIP_WRAP" ]]; then
        rm -f "$_TERMRECORD_PENDING_FILE"
        _termrecord_reset_state
        return $exit_code
    fi

    # Verify cast file was created
    if [[ ! -f "$_TERMRECORD_CAST_FILE" ]]; then
        rm -f "$_TERMRECORD_PENDING_FILE"
        _termrecord_reset_state
        return $exit_code
    fi

    local end_time=$(date +%s.%N)
    local duration=$(( end_time - _TERMRECORD_START_TIME ))

    # Get atuin ID for this command
    local atuin_id=""
    (( $+commands[atuin] )) && atuin_id=$(atuin history last --format "{id}" 2>/dev/null || echo "")

    # Create final metadata
    local meta_file="${_TERMRECORD_PENDING_FILE%.pending}.meta.json"
    local relative_cast="${_TERMRECORD_CAST_FILE#${_TERMRECORD_STORAGE}/recordings/}"

    # Read pending and augment with final data
    local pending_content=$(<"$_TERMRECORD_PENDING_FILE")

    echo "$pending_content" | jq \
        --arg atuin_id "$atuin_id" \
        --argjson exit_code "$exit_code" \
        --argjson duration "$duration" \
        --arg cast "$relative_cast" \
        '. + {
            atuin_id: $atuin_id,
            exit_code: $exit_code,
            duration: $duration,
            files: {
                cast: $cast,
                gif: null,
                screenshot: null
            }
        } | del(.cast_path)' > "$meta_file"

    rm -f "$_TERMRECORD_PENDING_FILE"
    _termrecord_reset_state

    return $exit_code
}

_termrecord_reset_state() {
    _TERMRECORD_RECORDING_ID=""
    _TERMRECORD_PENDING_FILE=""
    _TERMRECORD_CAST_FILE=""
    _TERMRECORD_START_TIME=""
    _TERMRECORD_SKIP_WRAP=""
    _TERMRECORD_ORIGINAL_CMD=""
}

# Register precmd hook
autoload -Uz add-zsh-hook
add-zsh-hook precmd _termrecord_precmd
