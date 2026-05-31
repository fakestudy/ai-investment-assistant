package tools

import (
	"context"

	einotool "github.com/cloudwego/eino/components/tool"
	toolutils "github.com/cloudwego/eino/components/tool/utils"
)

type EinoInvokableTool = einotool.InvokableTool

type webSearchInput struct {
	Query string `json:"query" jsonschema:"description=Search query for current market or company information,required"`
}

type fetchURLInput struct {
	URL string `json:"url" jsonschema:"description=HTTP or HTTPS URL to fetch,required"`
}

type currentTimeInput struct{}

func (r Registry) EinoTools(ctx context.Context) ([]EinoInvokableTool, error) {
	webSearch, err := toolutils.InferTool(
		"web_search",
		"Search the web for current information.",
		func(ctx context.Context, input webSearchInput) (map[string]any, error) {
			return r.Execute(ctx, "web_search", map[string]any{"query": input.Query})
		},
	)
	if err != nil {
		return nil, err
	}

	fetchURL, err := toolutils.InferTool(
		"fetch_url",
		"Fetch an HTTP or HTTPS URL and extract visible title and text.",
		func(ctx context.Context, input fetchURLInput) (map[string]any, error) {
			return r.Execute(ctx, "fetch_url", map[string]any{"url": input.URL})
		},
	)
	if err != nil {
		return nil, err
	}

	currentTime, err := toolutils.InferTool(
		"current_time",
		"Get the current date and time in Asia/Shanghai timezone.",
		func(ctx context.Context, input currentTimeInput) (map[string]any, error) {
			return r.Execute(ctx, "current_time", map[string]any{})
		},
	)
	if err != nil {
		return nil, err
	}

	return []EinoInvokableTool{webSearch, fetchURL, currentTime}, nil
}
