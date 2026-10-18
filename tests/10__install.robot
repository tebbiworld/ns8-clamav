*** Settings ***
Library     SSHLibrary
Resource    api.resource

*** Variables ***
${CONFIG}    {"listen_lan":false,"max_file_size_mb":100,"max_scan_size_mb":400,"stream_max_length_mb":100,"signature_checks_per_day":12,"web_host":"clamav.ci.test","lets_encrypt":false,"http2https":true,"web_user":"scan","web_password":"Scan#Pass 12","ip_allowlist":[]}

${CUSTOM_LDAP}    {"web_host":"clamav.ci.test","lets_encrypt":false,"http2https":true,"web_auth":"ldap","ldap_source":"custom","ldap_url":"ldaps://ldap.ci.test:636","ldap_tls_verify":true,"ldap_schema":"ad","ldap_base_dn":"DC=ci,DC=test","ldap_bind_dn":"CN=svc,DC=ci,DC=test","ldap_bind_password":"Bind#Pass 34","web_user":"scan","ip_allowlist":[]}

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

The login page works
    # only the image under test has the login page: in the update scenario
    # the checks above also ran against the previous release
    # a browser without a session is sent to the login page
    ${code} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code} \%{redirect_url}' -H 'Host: clamav.ci.test' https://127.0.0.1/
    Should Be Equal As Strings    ${code.strip()}    303 https://127.0.0.1/login
    # the login form sets the session cookie
    ${cookie} =    Run on node    curl -sSk -o /dev/null -D - -H 'Host: clamav.ci.test' --data-urlencode user=scan --data-urlencode 'password=Scan#Pass 12' https://127.0.0.1/login | grep -ci '^set-cookie: clamav_session='
    Should Be Equal As Strings    ${cookie.strip()}    1

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

The favicon is served without login
    ${out} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code} \%{content_type}' -H 'Host: clamav.ci.test' https://127.0.0.1/favicon.ico
    Should Be Equal As Strings    ${out.strip()}    200 image/png

The signature age is reported
    ${cfg} =    Run task    module/${module_id}/get-configuration    {}
    Should Be True    ${cfg['signature_age_hours']} is not None and ${cfg['signature_age_hours']} >= 0

Groups of an unknown user domain are an empty list
    ${out} =    Run task    module/${module_id}/list-ldap-groups    {"domain":"no-such-domain.ci.test"}
    Should Be Equal As Integers    ${{ len($out['groups']) }}    0

A custom LDAP server keeps its bind password out of the environment
    Run task    module/${module_id}/configure-module    ${CUSTOM_LDAP}    decode_json=${FALSE}
    ${cfg} =    Run task    module/${module_id}/get-configuration    {}
    Should Be Equal    ${cfg['web_auth']}    ldap
    Should Be Equal    ${cfg['ldap_source']}    custom
    Should Be Equal    ${cfg['ldap_url']}    ldaps://ldap.ci.test:636
    Should Be True    ${cfg['ldap_bind_password_set']}
    Should Be True    'ldap_bind_password' not in $cfg
    Secrets are kept out of the module environment    ${module_id}
    ${leaks} =    Run on node    runagent -m ${module_id} bash -c 'grep -c "Bind#Pass 34" "$AGENT_STATE_DIR/environment" || true'
    Should Be Equal As Integers    ${leaks.strip()}    0
    Wait Until Keyword Succeeds    30 times    5 seconds    The web front end uses the custom LDAP server

Back to the local login
    Run task    module/${module_id}/configure-module    ${CONFIG}    decode_json=${FALSE}
    Wait Until Keyword Succeeds    30 times    5 seconds    Daemon is up and the web login works

A scan writes a journal line
    Run on node    printf 'X5O!P%%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > /tmp/ci-eicar.txt
    Run on node    curl -sSk -o /dev/null -u 'scan:Scan#Pass 12' -F file=@/tmp/ci-eicar.txt -H 'Host: clamav.ci.test' https://127.0.0.1/api/v1/scan
    ${n} =    Run on node    runagent -m ${module_id} bash -c 'journalctl --user -u clamav-web --since -5min -o cat | grep -c "event=.scan. result=.infected." || true'
    Should Be True    ${n.strip()} >= 1

*** Keywords ***
Daemon is up and the web login works
    ${cfg} =    Run task    module/${module_id}/get-configuration    {}
    Should Be True    ${cfg['daemon_up']}
    # the API answers 401 without credentials and accepts basic auth (the
    # same in every release, so this also checks the previous one)
    ${code} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code}' -H 'Host: clamav.ci.test' https://127.0.0.1/api/v1/version
    Should Be Equal As Strings    ${code.strip()}    401
    ${code} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code}' -u 'scan:Scan#Pass 12' -H 'Host: clamav.ci.test' https://127.0.0.1/api/v1/version
    Should Be Equal As Strings    ${code.strip()}    200

The web front end uses the custom LDAP server
    # discover-ldap writes the connection, with the bind password, to a
    # private file outside the backup when clamav-web starts
    ${env} =    Run on node    runagent -m ${module_id} bash -c 'stat -c \%a "$AGENT_STATE_DIR/ldap.env"; grep -E "^LDAP_(SOURCE|HOST|PORT|TLS)=" "$AGENT_STATE_DIR/ldap.env" | sort | tr "\\n" " "'
    Should Be Equal As Strings    ${env.strip()}    600\nLDAP_HOST=ldap.ci.test LDAP_PORT=636 LDAP_SOURCE=custom LDAP_TLS=ssl
    # the server does not exist: every login is refused, the service stays up
    ${code} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code}' -u 'scan:Scan#Pass 12' -H 'Host: clamav.ci.test' https://127.0.0.1/api/v1/version
    Should Be Equal As Strings    ${code.strip()}    401
    ${code} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code}' -H 'Host: clamav.ci.test' https://127.0.0.1/api/v1/health
    Should Be Equal As Strings    ${code.strip()}    200
