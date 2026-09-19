*** Settings ***
Library     SSHLibrary
Resource    api.resource

*** Test Cases ***
Remove the module
    Run on node    remove-module --no-preserve ${module_id}
