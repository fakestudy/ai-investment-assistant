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

	server := bff.NewServer(bff.NewAgentGRPCClient(conn))
	log.Println("BFF listening on :8080")
	if err := http.ListenAndServe(":8080", server); err != nil {
		log.Fatal(err)
	}
}
