<!--
  Copyright (C) 2026 tebbi
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <cv-grid fullWidth>
    <cv-row>
      <cv-column class="page-title"><h2>{{ $t("settings.title") }}</h2></cv-column>
    </cv-row>
    <cv-row v-if="error.getConfiguration">
      <cv-column>
        <NsInlineNotification kind="error" :title="$t('action.get-configuration')" :description="error.getConfiguration" :showCloseButton="false" />
      </cv-column>
    </cv-row>
    <cv-row>
      <cv-column>
        <cv-tile light>
          <NsInlineNotification
            v-if="!loading.getConfiguration"
            :kind="daemon_up ? 'success' : 'warning'"
            :title="daemon_up ? $t('settings.daemon_up_title', { engine: engine_version }) : $t('settings.daemon_down_title')"
            :description="daemon_up ? $t('settings.daemon_up_desc', { sigs: signature_version, date: signature_date }) : $t('settings.daemon_down_desc')"
            :showCloseButton="false"
            class="info-tile"
          />
          <cv-form @submit.prevent="configureModule">
            <h4 class="section">{{ $t("settings.access_section") }}</h4>
            <cv-toggle value="listen_lan" :label="$t('settings.listen_lan')" v-model="listen_lan" :disabled="loading.getConfiguration || loading.configureModule" class="toggle">
              <template slot="text-left">{{ $t("settings.disabled") }}</template>
              <template slot="text-right">{{ $t("settings.enabled") }}</template>
            </cv-toggle>
            <div v-if="error.listen_lan" class="bx--form-requirement error-text">{{ $t(error.listen_lan) }}</div>
            <NsInlineNotification kind="info" :title="$t('settings.endpoints_title')" :showCloseButton="false" class="info-tile">
              <template #description>
                <div class="endpoints">
                  <div><strong>{{ $t("settings.ep_same_node_slirp") }}</strong> <code>10.0.2.2:{{ port }}</code></div>
                  <div><strong>{{ $t("settings.ep_same_node_pasta") }}</strong> <code>host.containers.internal:{{ port }}</code></div>
                  <div v-if="vpn_address"><strong>{{ $t("settings.ep_vpn") }}</strong> <code>{{ vpn_address }}:{{ port }}</code></div>
                  <div v-if="listen_lan && lan_addresses.length"><strong>{{ $t("settings.ep_lan") }}</strong> <code v-for="a in lan_addresses" :key="a">{{ a }}:{{ port }} </code></div>
                  <div class="ep-hint">{{ $t("settings.ep_hint") }}</div>
                </div>
              </template>
            </NsInlineNotification>

            <h4 class="section">{{ $t("settings.web_section") }}</h4>
            <cv-text-input :label="$t('settings.web_host')" v-model.trim="web_host" :placeholder="$t('settings.web_host_placeholder')" :helper-text="$t('settings.web_host_helper')" :disabled="loading.getConfiguration || loading.configureModule" :invalid-message="$t(error.web_host)" ref="web_host" class="field"></cv-text-input>
            <template v-if="web_host">
              <cv-toggle value="lets_encrypt" :label="$t('settings.lets_encrypt')" v-model="lets_encrypt" :disabled="loading.getConfiguration || loading.configureModule" class="toggle">
                <template slot="text-left">{{ $t("settings.disabled") }}</template>
                <template slot="text-right">{{ $t("settings.enabled") }}</template>
              </cv-toggle>
              <cv-toggle value="http2https" :label="$t('settings.http2https')" v-model="http2https" :disabled="loading.getConfiguration || loading.configureModule" class="toggle">
                <template slot="text-left">{{ $t("settings.disabled") }}</template>
                <template slot="text-right">{{ $t("settings.enabled") }}</template>
              </cv-toggle>
              <cv-radio-group :legend="$t('settings.web_auth')" vertical class="field">
                <cv-radio-button name="web_auth" value="ldap" v-model="web_auth" :label="$t('settings.web_auth_ldap')" :disabled="loading.getConfiguration || loading.configureModule || !user_domains.length" />
                <cv-radio-button name="web_auth" value="local" v-model="web_auth" :label="$t('settings.web_auth_local')" :disabled="loading.getConfiguration || loading.configureModule" />
                <cv-radio-button name="web_auth" value="none" v-model="web_auth" :label="$t('settings.web_auth_none')" :disabled="loading.getConfiguration || loading.configureModule" />
              </cv-radio-group>
              <template v-if="web_auth === 'ldap'">
                <cv-dropdown :label="$t('settings.ldap_domain')" v-model="ldap_domain" :invalid-message="$t(error.ldap_domain)" :disabled="loading.getConfiguration || loading.configureModule" ref="ldap_domain" class="field">
                  <cv-dropdown-item v-for="d in user_domains" :key="d" :value="d">{{ d }}</cv-dropdown-item>
                </cv-dropdown>
                <cv-text-input :label="$t('settings.ldap_group')" v-model.trim="ldap_group" :placeholder="$t('settings.ldap_group_placeholder')" :helper-text="$t('settings.ldap_group_helper')" :invalid-message="$t(error.ldap_group)" :disabled="loading.getConfiguration || loading.configureModule" ref="ldap_group" class="field"></cv-text-input>
              </template>
              <NsInlineNotification v-if="web_auth === 'none'" kind="warning" :title="$t('settings.web_auth_off_title')" :description="allowlistItems().length ? $t('settings.web_auth_off_allowlist') : $t('settings.web_auth_off_open')" :showCloseButton="false" class="info-tile" />
              <cv-text-input v-if="web_auth === 'local'" :label="$t('settings.web_user')" v-model.trim="web_user" :disabled="loading.getConfiguration || loading.configureModule" :invalid-message="$t(error.web_user)" ref="web_user" class="field"></cv-text-input>
              <cv-text-input v-if="web_auth === 'local'" type="password" :label="$t('settings.web_password')" v-model="web_password" :placeholder="web_password_set ? $t('settings.secret_keep_placeholder') : ''" :helper-text="web_password_set ? $t('settings.secret_is_set') : $t('settings.web_password_helper')" :password-hide-label="$t('settings.hide')" :password-show-label="$t('settings.show')" :disabled="loading.getConfiguration || loading.configureModule" :invalid-message="$t(error.web_password)" ref="web_password" class="field"></cv-text-input>
              <cv-text-area :label="$t('settings.ip_allowlist')" v-model="ip_allowlist" :placeholder="$t('settings.ip_allowlist_placeholder')" :helper-text="$t('settings.ip_allowlist_helper')" :invalid-message="$t(error.ip_allowlist)" :disabled="loading.getConfiguration || loading.configureModule" ref="ip_allowlist" rows="3" class="field"></cv-text-area>
              <NsInlineNotification v-if="web_url" kind="info" :title="$t('settings.web_url')" :showCloseButton="false" class="info-tile">
                <template #description>
                  <div class="endpoints">
                    <div>{{ $t("settings.web_url_desc") }} <code>{{ web_url }}</code></div>
                    <div>REST: <code>curl <template v-if="web_auth === 'local'">-u {{ web_user }}:••• </template><template v-else-if="web_auth === 'ldap'">-u &lt;user&gt;:••• </template>-F file=@document.pdf {{ web_url }}api/v1/scan</code></div>
                    <div class="ep-hint">{{ $t("settings.web_api_hint") }}</div>
                  </div>
                </template>
              </NsInlineNotification>
            </template>

            <h4 class="section">{{ $t("settings.limits_section") }}</h4>
            <cv-number-input :label="$t('settings.max_file_size_mb')" v-model="max_file_size_mb" :min="1" :max="4000" :helper-text="$t('settings.max_file_size_mb_helper')" :invalid-message="$t(error.max_file_size_mb)" :disabled="loading.getConfiguration || loading.configureModule" ref="max_file_size_mb" class="field"></cv-number-input>
            <cv-number-input :label="$t('settings.max_scan_size_mb')" v-model="max_scan_size_mb" :min="1" :max="4000" :helper-text="$t('settings.max_scan_size_mb_helper')" :invalid-message="$t(error.max_scan_size_mb)" :disabled="loading.getConfiguration || loading.configureModule" ref="max_scan_size_mb" class="field"></cv-number-input>
            <cv-number-input :label="$t('settings.stream_max_length_mb')" v-model="stream_max_length_mb" :min="1" :max="4000" :helper-text="$t('settings.stream_max_length_mb_helper')" :invalid-message="$t(error.stream_max_length_mb)" :disabled="loading.getConfiguration || loading.configureModule" ref="stream_max_length_mb" class="field"></cv-number-input>
            <cv-number-input :label="$t('settings.signature_checks_per_day')" v-model="signature_checks_per_day" :min="1" :max="48" :helper-text="$t('settings.signature_checks_per_day_helper')" :disabled="loading.getConfiguration || loading.configureModule" class="field"></cv-number-input>

            <NsInlineNotification kind="info" :title="$t('settings.nextcloud_hint_title')" :description="$t('settings.nextcloud_hint_desc')" :showCloseButton="false" class="info-tile" />

            <cv-row v-if="error.configureModule">
              <cv-column>
                <NsInlineNotification kind="error" :title="$t('action.configure-module')" :description="error.configureModule" :showCloseButton="false" />
              </cv-column>
            </cv-row>
            <NsButton kind="primary" :icon="Save20" :loading="loading.configureModule" :disabled="loading.getConfiguration || loading.configureModule">{{ $t("settings.save") }}</NsButton>
          </cv-form>
        </cv-tile>
      </cv-column>
    </cv-row>
  </cv-grid>
</template>

<script>
import to from "await-to-js";
import { mapState } from "vuex";
import { QueryParamService, UtilService, TaskService, IconService, PageTitleService } from "@nethserver/ns8-ui-lib";

export default {
  name: "Settings",
  mixins: [TaskService, IconService, UtilService, QueryParamService, PageTitleService],
  pageTitle() {
    return this.$t("settings.title") + " - " + this.appName;
  },
  data() {
    return {
      q: { page: "settings" },
      urlCheckInterval: null,
      listen_lan: false,
      max_file_size_mb: 100,
      max_scan_size_mb: 400,
      stream_max_length_mb: 100,
      signature_checks_per_day: 12,
      web_host: "",
      lets_encrypt: false,
      http2https: true,
      web_auth: "local",
      ldap_domain: "",
      ldap_group: "",
      user_domains: [],
      web_user: "scan",
      web_password: "",
      web_password_set: false,
      ip_allowlist: "",
      web_url: "",
      daemon_up: false,
      engine_version: "",
      signature_version: "",
      signature_date: "",
      port: 3310,
      vpn_address: "",
      lan_addresses: [],
      loading: { getConfiguration: false, configureModule: false },
      error: { getConfiguration: "", configureModule: "", listen_lan: "", max_file_size_mb: "", max_scan_size_mb: "", stream_max_length_mb: "", web_host: "", web_user: "", web_password: "", ldap_domain: "", ldap_group: "", ip_allowlist: "" },
    };
  },
  computed: { ...mapState(["instanceName", "core", "appName"]) },
  beforeRouteEnter(to, from, next) {
    next((vm) => {
      vm.watchQueryData(vm);
      vm.urlCheckInterval = vm.initUrlBindingForApp(vm, vm.q.page);
    });
  },
  beforeRouteLeave(to, from, next) {
    clearInterval(this.urlCheckInterval);
    next();
  },
  created() {
    this.getConfiguration();
  },
  methods: {
    async getConfiguration() {
      this.loading.getConfiguration = true;
      this.error.getConfiguration = "";
      const taskAction = "get-configuration";
      const eventId = this.getUuid();
      this.core.$root.$once(`${taskAction}-aborted-${eventId}`, this.getConfigurationAborted);
      this.core.$root.$once(`${taskAction}-completed-${eventId}`, this.getConfigurationCompleted);
      const res = await to(this.createModuleTaskForApp(this.instanceName, { action: taskAction, extra: { title: this.$t("action." + taskAction), isNotificationHidden: true, eventId } }));
      const err = res[0];
      if (err) {
        this.error.getConfiguration = this.getErrorMessage(err);
        this.loading.getConfiguration = false;
      }
    },
    getConfigurationAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.getConfiguration = this.$t("error.generic_error");
      this.loading.getConfiguration = false;
    },
    getConfigurationCompleted(taskContext, taskResult) {
      this.loading.getConfiguration = false;
      const c = taskResult.output;
      this.listen_lan = !!c.listen_lan;
      this.max_file_size_mb = c.max_file_size_mb || 100;
      this.max_scan_size_mb = c.max_scan_size_mb || 400;
      this.stream_max_length_mb = c.stream_max_length_mb || 100;
      this.signature_checks_per_day = c.signature_checks_per_day || 12;
      this.web_host = c.web_host || "";
      this.lets_encrypt = !!c.lets_encrypt;
      this.http2https = c.http2https !== undefined ? !!c.http2https : true;
      this.web_auth = c.web_auth || "local";
      this.user_domains = c.user_domains || [];
      this.ldap_domain = c.ldap_domain || (this.user_domains.length === 1 ? this.user_domains[0] : "");
      this.ldap_group = c.ldap_group || "";
      this.web_user = c.web_user || "scan";
      this.web_password_set = !!c.web_password_set;
      this.web_password = "";
      this.ip_allowlist = (c.ip_allowlist || []).join("\n");
      this.web_url = c.web_url || "";
      this.daemon_up = !!c.daemon_up;
      this.engine_version = c.engine_version || "";
      this.signature_version = c.signature_version || "";
      this.signature_date = c.signature_date || "";
      this.port = c.port || 3310;
      this.vpn_address = c.vpn_address || "";
      this.lan_addresses = c.lan_addresses || [];
    },
    allowlistItems() {
      return this.ip_allowlist.split(/[\s,]+/).map((x) => x.trim()).filter((x) => x);
    },
    validateConfigureModule() {
      this.clearErrors(this);
      let ok = true;
      const fail = (field, msg) => {
        this.error[field] = msg;
        if (ok) this.focusElement(field);
        ok = false;
      };
      for (const f of ["max_file_size_mb", "max_scan_size_mb", "stream_max_length_mb"]) {
        const v = Number(this[f]);
        if (!Number.isInteger(v) || v < 1 || v > 4000) fail(f, "settings.size_out_of_range");
      }
      if (Number(this.stream_max_length_mb) < Number(this.max_file_size_mb)) fail("stream_max_length_mb", "settings.stream_smaller_than_file");
      if (this.web_host) {
        if (this.web_auth === "ldap" && !this.ldap_domain) fail("ldap_domain", "common.required");
        if (this.web_auth === "local") {
          if (!this.web_user) fail("web_user", "common.required");
          if (!this.web_password && !this.web_password_set) fail("web_password", "common.required");
          if (this.web_password && this.web_password.length < 8) fail("web_password", "settings.web_password_too_short");
        }
        const cidr = /^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$|^[0-9a-fA-F:]+(\/\d{1,3})?$/;
        if (this.allowlistItems().some((c) => !cidr.test(c))) fail("ip_allowlist", "settings.invalid_cidr");
      }
      return ok;
    },
    configureModuleValidationFailed(validationErrors) {
      this.loading.configureModule = false;
      let focusSet = false;
      for (const e of validationErrors) {
        if (e.field !== "(root)") {
          this.error[e.field] = this.$t("settings." + e.error);
          if (!focusSet) {
            this.focusElement(e.field);
            focusSet = true;
          }
        }
      }
    },
    async configureModule() {
      if (!this.validateConfigureModule()) return;
      this.loading.configureModule = true;
      const taskAction = "configure-module";
      const eventId = this.getUuid();
      this.core.$root.$once(`${taskAction}-aborted-${eventId}`, this.configureModuleAborted);
      this.core.$root.$once(`${taskAction}-validation-failed-${eventId}`, this.configureModuleValidationFailed);
      this.core.$root.$once(`${taskAction}-completed-${eventId}`, this.configureModuleCompleted);
      const data = {
        listen_lan: this.listen_lan,
        max_file_size_mb: Number(this.max_file_size_mb),
        max_scan_size_mb: Number(this.max_scan_size_mb),
        stream_max_length_mb: Number(this.stream_max_length_mb),
        signature_checks_per_day: Number(this.signature_checks_per_day),
        web_host: this.web_host,
        lets_encrypt: this.lets_encrypt,
        http2https: this.http2https,
        web_auth: this.web_auth,
        ldap_domain: this.web_auth === "ldap" ? this.ldap_domain : "",
        ldap_group: this.ldap_group,
        web_user: this.web_user,
        web_password: this.web_password,
        ip_allowlist: this.allowlistItems(),
      };
      const res = await to(this.createModuleTaskForApp(this.instanceName, {
        action: taskAction,
        data,
        extra: { title: this.$t("settings.configure_instance", { instance: this.instanceName }), description: this.$t("common.processing"), eventId },
      }));
      const err = res[0];
      if (err) {
        this.error.configureModule = this.getErrorMessage(err);
        this.loading.configureModule = false;
      }
    },
    configureModuleAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.configureModule = this.$t("error.generic_error");
      this.loading.configureModule = false;
    },
    configureModuleCompleted() {
      this.loading.configureModule = false;
      this.getConfiguration();
    },
  },
};
</script>

<style scoped lang="scss">
@import "../styles/carbon-utils";
.field { margin-top: $spacing-06; }
.toggle { margin-top: $spacing-06; }
.info-tile { margin-top: $spacing-06; }
.section { margin-top: $spacing-07; margin-bottom: $spacing-03; }
.error-text { display: block; color: #da1e28; margin-top: $spacing-03; }
.endpoints div { margin-top: $spacing-02; }
.endpoints code { font-family: monospace; }
.endpoints .ep-hint { margin-top: $spacing-04; }
</style>
