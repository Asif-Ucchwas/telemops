resource "kubernetes_deployment" "can_publisher" {
  metadata {
    name = "can-publisher"
  }
  spec {
    replicas = 1
    selector {
      match_labels = { app = "can-publisher" }
    }
    template {
      metadata {
        labels = { app = "can-publisher" }
      }
      spec {
        host_network = true
        dns_policy   = "ClusterFirstWithHostNet"
        container {
          name              = "can-publisher"
          image             = "telemops-ingestion:latest"
          image_pull_policy = "Never"
          command           = ["python", "can_publisher.py"]
        }
      }
    }
  }
}

resource "kubernetes_deployment" "ingestor" {
  metadata {
    name = "ingestor"
  }
  spec {
    replicas = 1
    selector {
      match_labels = { app = "ingestor" }
    }
    template {
      metadata {
        labels = { app = "ingestor" }
      }
      spec {
        host_network = true
        dns_policy   = "ClusterFirstWithHostNet"
        container {
          name              = "ingestor"
          image             = "telemops-ingestion:latest"
          image_pull_policy = "Never"
          command           = ["python", "ingest.py"]
          env {
            name  = "DB_HOST"
            value = "192.168.49.2"
          }
          env {
            name  = "DB_PORT"
            value = "30432"
          }
        }
      }
    }
  }
}
