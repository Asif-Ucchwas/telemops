resource "kubernetes_persistent_volume_claim" "grafana" {
  metadata {
    name = "grafana-pvc"
  }
  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "500Mi"
      }
    }
  }
}

resource "kubernetes_deployment" "grafana" {
  metadata {
    name = "grafana"
  }
  spec {
    replicas = 1
    selector {
      match_labels = { app = "grafana" }
    }
    template {
      metadata {
        labels = { app = "grafana" }
      }
      spec {
        container {
          name              = "grafana"
          image             = "telemops-grafana:latest"
          image_pull_policy = "Never"
          port {
            container_port = 3000
          }
          env {
            name  = "GF_SECURITY_ADMIN_USER"
            value = "admin"
          }
          env {
            name  = "GF_SECURITY_ADMIN_PASSWORD"
            value = "telemops_admin"
          }
          volume_mount {
            name       = "grafana-storage"
            mount_path = "/var/lib/grafana"
          }
        }
        volume {
          name = "grafana-storage"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim.grafana.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "grafana" {
  metadata {
    name = "grafana"
  }
  spec {
    type     = "NodePort"
    selector = { app = "grafana" }
    port {
      port        = 3000
      target_port = 3000
      node_port   = 30300
    }
  }
}
