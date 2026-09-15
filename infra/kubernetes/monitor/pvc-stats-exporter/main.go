package main

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

const (
	tokenPath = "/var/run/secrets/kubernetes.io/serviceaccount/token"
	caPath    = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
)

type nodeList struct {
	Items []struct {
		Metadata struct {
			Name string `json:"name"`
		} `json:"metadata"`
	} `json:"items"`
}

type statsSummary struct {
	Pods []struct {
		PodRef struct {
			Namespace string `json:"namespace"`
		} `json:"podRef"`
		Volume []struct {
			Name           string `json:"name"`
			UsedBytes      *int64 `json:"usedBytes"`
			CapacityBytes  *int64 `json:"capacityBytes"`
			PvcRef         *struct {
				Name      string `json:"name"`
				Namespace string `json:"namespace"`
			} `json:"pvcRef"`
		} `json:"volume"`
	} `json:"pods"`
}

func apiClient() (*http.Client, error) {
	ca, err := os.ReadFile(caPath)
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(ca) {
		return nil, fmt.Errorf("failed to parse serviceaccount CA")
	}
	return &http.Client{
		Timeout: 20 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{RootCAs: pool},
		},
	}, nil
}

func apiGet(client *http.Client, token, path string, dest any) error {
	host := os.Getenv("KUBERNETES_SERVICE_HOST")
	port := os.Getenv("KUBERNETES_SERVICE_PORT")
	req, err := http.NewRequest(http.MethodGet, "https://"+host+":"+port+path, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(token))
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("%s: %s", resp.Status, string(body))
	}
	return json.Unmarshal(body, dest)
}

func collect() (string, error) {
	token, err := os.ReadFile(tokenPath)
	if err != nil {
		return "", err
	}
	client, err := apiClient()
	if err != nil {
		return "", err
	}

	var nodes nodeList
	if err := apiGet(client, string(token), "/api/v1/nodes", &nodes); err != nil {
		return "", err
	}

	var b strings.Builder
	b.WriteString("# HELP pvc_stats_used_bytes PVC used bytes from kubelet stats/summary\n")
	b.WriteString("# TYPE pvc_stats_used_bytes gauge\n")
	b.WriteString("# HELP pvc_stats_capacity_bytes PVC capacity bytes from kubelet stats/summary\n")
	b.WriteString("# TYPE pvc_stats_capacity_bytes gauge\n")

	seen := map[string]struct{}{}
	for _, n := range nodes.Items {
		name := n.Metadata.Name
		var summary statsSummary
		if err := apiGet(client, string(token), "/api/v1/nodes/"+name+"/proxy/stats/summary", &summary); err != nil {
			continue
		}
		for _, pod := range summary.Pods {
			ns := pod.PodRef.Namespace
			for _, vol := range pod.Volume {
				if vol.PvcRef == nil || vol.PvcRef.Name == "" || vol.UsedBytes == nil || vol.CapacityBytes == nil || *vol.CapacityBytes == 0 {
					continue
				}
				pvcNS := vol.PvcRef.Namespace
				if pvcNS == "" {
					pvcNS = ns
				}
				key := pvcNS + "/" + vol.PvcRef.Name
				if _, ok := seen[key]; ok {
					continue
				}
				seen[key] = struct{}{}
				fmt.Fprintf(&b, "pvc_stats_used_bytes{namespace=%q,persistentvolumeclaim=%q} %d\n", pvcNS, vol.PvcRef.Name, *vol.UsedBytes)
				fmt.Fprintf(&b, "pvc_stats_capacity_bytes{namespace=%q,persistentvolumeclaim=%q} %d\n", pvcNS, vol.PvcRef.Name, *vol.CapacityBytes)
			}
		}
	}
	return b.String(), nil
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "9100"
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		body, err := collect()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		_, _ = w.Write([]byte(body))
	})
	_ = http.ListenAndServe(":"+port, mux)
}
