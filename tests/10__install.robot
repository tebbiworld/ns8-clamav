*** Settings ***
Library     SSHLibrary
Resource    api.resource

*** Variables ***
${CONFIG}    {"listen_lan":false,"max_file_size_mb":100,"max_scan_size_mb":400,"stream_max_length_mb":100,"signature_checks_per_day":12,"web_host":"clamav.ci.test","lets_encrypt":false,"http2https":true,"web_user":"scan","web_password":"Scan#Pass 12","ip_allowlist":[]}

*** Test Cases ***
Install the module
    IF    '${SCENARIO}' == 'update'
        ${output}  ${rc} =    Execute Command    add-module ${UPDATE_FROM} 1    return_rc=True
    ELSE
        ${output}  ${rc} =    Execute Command    add-module ${IMAGE_URL} 1    return_rc=True
    END
    Should Be Equal As Integers    ${rc}  0
    &{output} =    Evaluate    ${output}
    Set Global Variable    ${module_id}    ${output.module_id}

Configure the module
    Run task    module/${module_id}/configure-module    ${CONFIG}    decode_json=${FALSE}

The scanner and the web front end are up
    # freshclam downloads the signature database before clamd starts
    Wait Until Keyword Succeeds    90 times    10 seconds    Daemon is up and the web login works

Update to the image under test
    Skip If    '${SCENARIO}' != 'update'    scenario is ${SCENARIO}
    Run on node    api-cli run update-module --data '{"force":true,"module_url":"${IMAGE_URL}","instances":["${module_id}"]}'
    # the migrated password hash must still accept the same password
    Wait Until Keyword Succeeds    90 times    10 seconds    Daemon is up and the web login works

Configuration reads back
    ${cfg} =    Run task    module/${module_id}/get-configuration    {}
    Should Be Equal    ${cfg['web_host']}    clamav.ci.test
    Should Be Equal    ${cfg['web_user']}    scan
    Should Be True    ${cfg['web_password_set']}

Secrets are stored in passwords.env only
    Secrets are kept out of the module environment    ${module_id}
    ${leaks} =    Run on node    runagent -m ${module_id} bash -c 'grep -c PBKDF2 "$AGENT_STATE_DIR/environment" || true'
    Should Be Equal As Integers    ${leaks.strip()}    0
    ${mode} =    Run on node    runagent -m ${module_id} bash -c 'stat -c \%a "$AGENT_STATE_DIR/clamav-web.env"'
    Should Be Equal As Strings    ${mode.strip()}    600

*** Keywords ***
Daemon is up and the web login works
    ${cfg} =    Run task    module/${module_id}/get-configuration    {}
    Should Be True    ${cfg['daemon_up']}
    ${code} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code}' -H 'Host: clamav.ci.test' https://127.0.0.1/
    Should Be Equal As Strings    ${code.strip()}    401
    ${code} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code}' -u 'scan:Scan#Pass 12' -H 'Host: clamav.ci.test' https://127.0.0.1/
    Should Be Equal As Strings    ${code.strip()}    200
