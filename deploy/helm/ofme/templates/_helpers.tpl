{{/* Common template helpers for the OFME chart. */}}

{{- define "ofme.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ofme.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "ofme.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "ofme.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fixed service names: the SPA nginx configuration proxies to ofme-api:8000. */}}
{{- define "ofme.componentName" -}}
{{- printf "ofme-%s" (index . 1) -}}
{{- end -}}

{{- define "ofme.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "ofme.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "ofme.labels" -}}
helm.sh/chart: {{ include "ofme.chart" . }}
app.kubernetes.io/name: {{ include "ofme.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: ofme
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{- define "ofme.selectorLabels" -}}
{{- $root := index . 0 -}}
app.kubernetes.io/name: {{ include "ofme.name" $root }}
app.kubernetes.io/instance: {{ $root.Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end -}}

{{- define "ofme.image" -}}
{{- $root := index . 0 -}}
{{- $component := index . 1 -}}
{{- $image := index $root.Values.image $component -}}
{{- printf "%s:%s" $image.repository (default $root.Chart.AppVersion $image.tag) -}}
{{- end -}}

{{/* Environment entries backed by the application secret. */}}
{{- define "ofme.secretEnv" -}}
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret }}
      key: SECRET_KEY
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret }}
      key: DATABASE_URL
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret }}
      key: REDIS_URL
- name: CELERY_BROKER_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret }}
      key: CELERY_BROKER_URL
- name: CELERY_RESULT_BACKEND
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret }}
      key: CELERY_RESULT_BACKEND
- name: S3_ENDPOINT
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret }}
      key: S3_ENDPOINT
- name: S3_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret }}
      key: S3_ACCESS_KEY
- name: S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.secrets.existingSecret }}
      key: S3_SECRET_KEY
{{- end -}}
