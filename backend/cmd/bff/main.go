package main

import (
	"log"
	"net/http"
	"os"

	"github.com/bytedance/ai-investment-assistant/backend/internal/bff"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func main() {
	agentAddr := os.Getenv("AGENT_GRPC_ADDR")
	if agentAddr == "" {
		agentAddr = "127.0.0.1:9010"
	}
	conn, err := grpc.NewClient(agentAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()

	httpAddr := bffHTTPAddr()
	server := bff.NewServer(bff.NewAgentGRPCClient(conn))
	log.Printf("BFF listening on %s", httpAddr)
	if err := http.ListenAndServe(httpAddr, server); err != nil {
		log.Fatal(err)
	}
}

func bffHTTPAddr() string {
	httpAddr := os.Getenv("BFF_HTTP_ADDR")
	if httpAddr == "" {
		return ":8081"
	}
	return httpAddr
}
