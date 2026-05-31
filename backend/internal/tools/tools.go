package tools

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"ai-investment-assistant/backend/internal/config"

	"golang.org/x/net/html"
)

type HTTPDoer interface {
	Do(req *http.Request) (*http.Response, error)
}

type Tool func(ctx context.Context, args map[string]any) (map[string]any, error)

type Registry struct {
	tools map[string]Tool
}

func NewRegistry(cfg config.Config) Registry {
	client := newHTTPClient(cfg)
	return Registry{tools: map[string]Tool{
		"web_search":   newWebSearchTool(cfg, client),
		"fetch_url":    newFetchURLTool(client, cfg.FetchAllowPrivate),
		"current_time": newCurrentTimeTool(),
	}}
}

func newHTTPClient(cfg config.Config) *http.Client {
	timeout := cfg.HTTPClientTimeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			DialContext: safeDialContext(cfg.FetchAllowPrivate),
		},
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return validateFetchURL(req.URL, cfg.FetchAllowPrivate)
		},
	}
}

func webSearchTool(cfg config.Config, client *http.Client) {

}

func newCurrentTimeTool() Tool {
	return func(_ context.Context, _ map[string]any) (map[string]any, error) {
		location, err := time.LoadLocation("Asia/Shanghai")
		if err != nil {
			return nil, err
		}
		now := time.Now().In(location)
		return map[string]any{
			"timezone": "Asia/Shanghai",
			"unix":     now.Unix(),
			"iso8601":  now.Format(time.RFC3339),
			"date":     now.Format("2006-01-02"),
			"time":     now.Format("15:04:05"),
		}, nil
	}
}

func safeDialContext(allowPrivate bool) func(context.Context, string, string) (net.Conn, error) {
	dialer := &net.Dialer{}
	return func(ctx context.Context, network string, address string) (net.Conn, error) {
		host, port, err := net.SplitHostPort(address)
		if err != nil {
			return nil, err
		}
		if allowPrivate {
			return dialer.DialContext(ctx, network, address)
		}
		ips, err := net.DefaultResolver.LookupIPAddr(ctx, host)
		if err != nil {
			return nil, fmt.Errorf("resolve host: %w", err)
		}
		var lastErr error
		for _, resolved := range ips {
			if isPrivateAddress(resolved.IP) {
				return nil, fmt.Errorf("fetch_url blocked private address %s", resolved.IP.String())
			}
			conn, err := dialer.DialContext(ctx, network, net.JoinHostPort(resolved.IP.String(), port))
			if err == nil {
				return conn, nil
			}
			lastErr = err
		}
		if lastErr != nil {
			return nil, lastErr
		}
		return nil, errors.New("host resolved to no addresses")
	}
}

func (r Registry) Execute(ctx context.Context, name string, args map[string]any) (map[string]any, error) {
	tool, ok := r.tools[name]
	if !ok {
		return nil, fmt.Errorf("unknown tool %q", name)
	}
	return tool(ctx, args)
}

func newFetchURLTool(client HTTPDoer, allowPrivate bool) Tool {
	return func(ctx context.Context, args map[string]any) (map[string]any, error) {
		rawURL := strings.TrimSpace(stringArg(args, "url"))
		parsed, err := url.Parse(rawURL)
		if err != nil {
			return nil, errors.New("url must be a valid http:// or https:// URL")
		}
		if err := validateFetchURL(parsed, allowPrivate); err != nil {
			return nil, err
		}
		if parsed.Scheme == "" || parsed.Host == "" {
			return nil, errors.New("url must be a valid http:// or https:// URL")
		}
		if parsed.Scheme != "http" && parsed.Scheme != "https" {
			return nil, errors.New("url must use http:// or https://")
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodGet, parsed.String(), nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("User-Agent", "ai-investment-assistant/1.0")
		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return nil, fmt.Errorf("fetch_url status %d", resp.StatusCode)
		}
		body, err := io.ReadAll(io.LimitReader(resp.Body, 256*1024))
		if err != nil {
			return nil, err
		}
		title, text := extractHTMLText(string(body))
		return map[string]any{
			"url":   parsed.String(),
			"title": title,
			"text":  text,
		}, nil
	}
}

func validateFetchURL(parsed *url.URL, allowPrivate bool) error {
	if parsed == nil || parsed.Scheme == "" || parsed.Host == "" {
		return errors.New("url must be a valid http:// or https:// URL")
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return errors.New("url must use http:// or https://")
	}
	if allowPrivate {
		return nil
	}
	host := parsed.Hostname()
	if host == "" {
		return errors.New("url must include a host")
	}
	ips, err := net.LookupIP(host)
	if err != nil {
		return fmt.Errorf("resolve host: %w", err)
	}
	for _, ip := range ips {
		if isPrivateAddress(ip) {
			return fmt.Errorf("fetch_url blocked private address %s", ip.String())
		}
	}
	return nil
}

func isPrivateAddress(ip net.IP) bool {
	if ip == nil {
		return true
	}
	return ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || ip.IsUnspecified()
}

func stringArg(args map[string]any, key string) string {
	if args == nil {
		return ""
	}
	value, ok := args[key]
	if !ok || value == nil {
		return ""
	}
	switch typed := value.(type) {
	case string:
		return typed
	default:
		return fmt.Sprint(typed)
	}
}

func extractHTMLText(raw string) (string, string) {
	doc, err := html.Parse(strings.NewReader(raw))
	if err != nil {
		return "", collapseWhitespace(stripTags(raw))
	}
	var title string
	var parts []string
	var walk func(*html.Node, bool)
	walk = func(n *html.Node, hidden bool) {
		if n.Type == html.ElementNode {
			name := strings.ToLower(n.Data)
			if name == "script" || name == "style" || name == "noscript" {
				hidden = true
			}
			if name == "title" {
				title = strings.TrimSpace(nodeText(n))
				hidden = true
			}
		}
		if !hidden && n.Type == html.TextNode {
			if text := strings.TrimSpace(n.Data); text != "" {
				parts = append(parts, text)
			}
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			walk(child, hidden)
		}
	}
	walk(doc, false)
	return title, collapseWhitespace(strings.Join(parts, " "))
}

func nodeText(n *html.Node) string {
	var parts []string
	var walk func(*html.Node)
	walk = func(current *html.Node) {
		if current.Type == html.TextNode {
			parts = append(parts, current.Data)
		}
		for child := current.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	walk(n)
	return strings.Join(parts, " ")
}

var tagPattern = regexp.MustCompile(`<[^>]+>`)
var whitespacePattern = regexp.MustCompile(`\s+`)

func stripTags(raw string) string {
	return tagPattern.ReplaceAllString(raw, " ")
}

func collapseWhitespace(raw string) string {
	return strings.TrimSpace(whitespacePattern.ReplaceAllString(raw, " "))
}
