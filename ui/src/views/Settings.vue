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
                  <div class="hint">{{ $t("settings.ep_hint") }}</div>
                </div>
              </template>
            </NsInlineNotification>

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
      daemon_up: false,
      engine_version: "",
      signature_version: "",
      signature_date: "",
      port: 3310,
      vpn_address: "",
      lan_addresses: [],
      loading: { getConfiguration: false, configureModule: false },
      error: { getConfiguration: "", configureModule: "", listen_lan: "", max_file_size_mb: "", max_scan_size_mb: "", stream_max_length_mb: "" },
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
      this.daemon_up = !!c.daemon_up;
      this.engine_version = c.engine_version || "";
      this.signature_version = c.signature_version || "";
      this.signature_date = c.signature_date || "";
      this.port = c.port || 3310;
      this.vpn_address = c.vpn_address || "";
      this.lan_addresses = c.lan_addresses || [];
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
.endpoints .hint { margin-top: $spacing-04; }
</style>
