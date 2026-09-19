*** Settings ***
Library     SSHLibrary
Resource    api.resource

*** Test Cases ***
Back up the module
    ${repo}    ${path} =    Back up the module to the cluster repository    ${module_id}
    Set Global Variable    ${BACKUP_REPO}    ${repo}
    Set Global Variable    ${BACKUP_PATH}    ${path}

Remove the original instance
    # org.nethserver.max-per-node=1: a second instance is refused while the first exists.
    # After the removal wait out logind's user stop delay: on Rocky 9 (systemd 252) a
    # module re-created within seconds gets the same UID back, the user manager for that
    # UID is not started again and the agent of the new instance never comes up.
    Run on node    remove-module --no-preserve ${module_id}
    Sleep    45s

Restore into a new instance
    ${rid} =    Restore the module from the cluster repository    ${BACKUP_REPO}    ${BACKUP_PATH}
    Set Global Variable    ${restored_id}    ${rid}
    Set Global Variable    ${module_id}    ${rid}

The restored instance has settings and secrets
    ${cfg} =    Run task    module/${restored_id}/get-configuration    {}
    Should Be Equal    ${cfg['web_host']}    clamav.ci.test
    Should Be Equal    ${cfg['web_user']}    scan
    Should Be True    ${cfg['web_password_set']}
    Secrets are kept out of the module environment    ${restored_id}
    Wait Until Keyword Succeeds    90 times    10 seconds    Restored web login works

*** Keywords ***
Restored web login works
    ${code} =    Run on node    curl -sSk -o /dev/null -w '\%{http_code}' -u 'scan:Scan#Pass 12' -H 'Host: clamav.ci.test' https://127.0.0.1/
    Should Be Equal As Strings    ${code.strip()}    200
