// Footnote — Azure Container Apps infrastructure
// Deploys: ACR, Storage (SMB), Log Analytics, Container Apps Environment,
//          API app, Web app, Pipeline scheduled job

@description('Location for all resources')
param location string = resourceGroup().location

@description('Prefix for resource names')
param namePrefix string = 'ftn'

@secure()
@description('API key for the cloud LLM scoring endpoint')
param cloudApiKey string

@description('URL of the cloud LLM scoring endpoint (e.g. Ollama-compatible)')
param cloudOllamaUrl string

@description('Cloud LLM model name')
param cloudModel string = 'glm-5.1'

@description('Days to backfill on first scan')
param backfillDays int = 90

@description('Git clone depth for shallow clones')
param cloneDepth int = 2000

@description('Cron expression for the pipeline schedule')
param pipelineCron string = '0 6 * * *'

@description('Pre-filter score threshold (0-10)')
param prefilterThreshold int = 3

@description('Minimum score to persist a change to the DB')
param minStoreScore string = '0.0'

// Unique suffix to avoid name collisions
var uniqueSuffix = uniqueString(resourceGroup().id)
var acrName = '${namePrefix}${uniqueSuffix}acr'
var storageName = '${namePrefix}${uniqueSuffix}st'
var logAnalyticsName = '${namePrefix}-logs'
var identityName = '${namePrefix}-identity'
var envName = '${namePrefix}-env'
var apiAppName = '${namePrefix}-api'
var webAppName = '${namePrefix}-web'
var pipelineJobName = '${namePrefix}-pipeline'

var dbShareName = 'dbdata'
var repoShareName = 'repodata'
var acrLoginServer = '${acrName}.azurecr.io'

// User-assigned managed identity — avoids circular dependency for ACR pull
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-07-31-preview' = {
  name: identityName
  location: location
}

// Container Registry
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

// Grant the managed identity AcrPull on the registry (scoped to the ACR resource)
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, 'AcrPull')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
  scope: acr
}
// Storage account for SMB file shares
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

// File service (required parent for file shares)
resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

// File shares
resource dbFileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: dbShareName
  properties: {
    shareQuota: 1
    enabledProtocols: 'SMB'
  }
}

resource repoFileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: repoShareName
  properties: {
    shareQuota: 50
    enabledProtocols: 'SMB'
  }
}

// Log Analytics Workspace
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// Container Apps Environment
resource env 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// Storage mounts on the environment (SMB — correct for SQLite file locking)
resource dbStorage 'Microsoft.App/managedEnvironments/storages@2024-10-02-preview' = {
  parent: env
  name: dbShareName
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: dbShareName
      accessMode: 'ReadWrite'
    }
  }
}

resource repoStorage 'Microsoft.App/managedEnvironments/storages@2024-10-02-preview' = {
  parent: env
  name: repoShareName
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: repoShareName
      accessMode: 'ReadWrite'
    }
  }
}

// API Container App
resource apiApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: apiAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    environmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: acrLoginServer
          identity: identity.id
        }
      ]
      secrets: [
        {
          name: 'ingest-token'
          value: cloudApiKey
        }
      ]
      ingress: {
        external: false
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: apiAppName
          image: '${acrLoginServer}/footnote-api:latest'
          env: [
            {
              name: 'DB_PATH'
              value: '/data/db/footnote.db'
            }
            {
              name: 'API_HOST'
              value: '0.0.0.0'
            }
            {
              name: 'API_PORT'
              value: '8000'
            }
            {
              name: 'INGEST_TOKEN'
              secretRef: 'ingest-token'
            }
          ]
          resources: {
            cpu: json('1.0')
            memory: '2.0Gi'
          }
          volumeMounts: [
            {
              volumeName: dbShareName
              mountPath: '/data/db'
            }
          ]
        }
      ]
      volumes: [
        {
          name: dbShareName
          storageType: 'AzureFile'
          storageName: dbShareName
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    dbStorage
    acrPull
  ]
}

// Web (frontend) Container App
resource webApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: webAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    environmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: acrLoginServer
          identity: identity.id
        }
      ]
      ingress: {
        external: true
        targetPort: 80
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: webAppName
          image: '${acrLoginServer}/footnote-web:latest'
          env: [
            {
              name: 'API_UPSTREAM'
              value: 'ftn-api:80'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    acrPull
  ]
}

// Pipeline scheduled job
resource pipelineJob 'Microsoft.App/jobs@2024-10-02-preview' = {
  name: pipelineJobName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Schedule'
      scheduleTriggerConfig: {
        cronExpression: pipelineCron
        parallelism: 1
        replicaCompletionCount: 1
      }
      replicaTimeout: 3600
      replicaRetryLimit: 1
      registries: [
        {
          server: acrLoginServer
          identity: identity.id
        }
      ]
      secrets: [
        {
          name: 'cloud-api-key'
          value: cloudApiKey
        }
        {
          name: 'ingest-token'
          value: cloudApiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: pipelineJobName
          image: '${acrLoginServer}/footnote-pipeline:latest'
          command: [
            'python'
          ]
          args: [
            'pipeline.py'
          ]
          env: [
            {
              name: 'API_URL'
              value: 'http://ftn-api:80'
            }
            {
              name: 'INGEST_TOKEN'
              secretRef: 'ingest-token'
            }
            {
              name: 'DATA_DIR'
              value: '/data/repos'
            }
            {
              name: 'CONFIG_PATH'
              value: 'repos.json'
            }
            {
              name: 'BACKFILL_DAYS'
              value: string(backfillDays)
            }
            {
              name: 'CLONE_DEPTH'
              value: string(cloneDepth)
            }
            {
              name: 'GIT_CONFIG_COUNT'
              value: '2'
            }
            {
              name: 'GIT_CONFIG_KEY_0'
              value: 'core.compression'
            }
            {
              name: 'GIT_CONFIG_VALUE_0'
              value: '0'
            }
            {
              name: 'GIT_CONFIG_KEY_1'
              value: 'pack.windowMemory'
            }
            {
              name: 'GIT_CONFIG_VALUE_1'
              value: '100m'
            }
            {
              name: 'TMPDIR'
              value: '/data/repos/.tmp'
            }
            {
              name: 'CLOUD_OLLAMA_URL'
              value: cloudOllamaUrl
            }
            {
              name: 'CLOUD_MODEL'
              value: cloudModel
            }
            {
              name: 'CLOUD_API_KEY'
              secretRef: 'cloud-api-key'
            }
            {
              name: 'PREFILTER_THRESHOLD'
              value: string(prefilterThreshold)
            }
            {
              name: 'MIN_STORE_SCORE'
              value: minStoreScore
            }
          ]
          resources: {
            cpu: json('2.0')
            memory: '4.0Gi'
          }
          volumeMounts: [
            {
              volumeName: repoShareName
              mountPath: '/data/repos'
            }
          ]
        }
      ]
      volumes: [
        {
          name: repoShareName
          storageType: 'AzureFile'
          storageName: repoShareName
        }
      ]
    }
  }
  dependsOn: [
    repoStorage
    acrPull
  ]
}

// Outputs
output webFqdn string = webApp.properties.configuration.?ingress.?fqdn ?? ''
output acrLoginServer string = acrLoginServer
output identityPrincipalId string = identity.properties.principalId
