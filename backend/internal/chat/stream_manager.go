package chat

import (
	"context"
	"sync"

	"ai-investment-assistant/backend/internal/conversation"
)

const streamSubscriberBuffer = 64

type streamManager struct {
	mu      sync.Mutex
	streams map[string]*activeStream
}

type activeStream struct {
	mu          sync.Mutex
	cancel      context.CancelFunc
	events      []StreamEvent
	subscribers map[chan StreamEvent]struct{}
	done        bool
}

func newStreamManager() *streamManager {
	return &streamManager{
		streams: map[string]*activeStream{},
	}
}

func (m *streamManager) start(messageID string, cancel context.CancelFunc) *activeStream {
	stream := &activeStream{
		cancel:      cancel,
		subscribers: map[chan StreamEvent]struct{}{},
	}

	m.mu.Lock()
	m.streams[messageID] = stream
	m.mu.Unlock()

	return stream
}

func (m *streamManager) subscribe(ctx context.Context, messageID string) (<-chan StreamEvent, error) {
	m.mu.Lock()
	stream, ok := m.streams[messageID]
	m.mu.Unlock()
	if !ok {
		return nil, conversation.ErrNotFound
	}

	replay, unsubscribe := stream.subscribe()
	output := make(chan StreamEvent)
	go func() {
		defer unsubscribe()
		defer close(output)
		for {
			select {
			case <-ctx.Done():
				return
			case event, ok := <-replay:
				if !ok {
					return
				}
				select {
				case <-ctx.Done():
					return
				case output <- event:
				}
			}
		}
	}()

	return output, nil
}

func (m *streamManager) cancel(messageID string) error {
	m.mu.Lock()
	stream, ok := m.streams[messageID]
	m.mu.Unlock()
	if !ok {
		return conversation.ErrNotFound
	}
	stream.cancel()
	return nil
}

func (m *streamManager) finish(messageID string, stream *activeStream) {
	stream.complete()

	m.mu.Lock()
	if m.streams[messageID] == stream {
		delete(m.streams, messageID)
	}
	m.mu.Unlock()
}

func (s *activeStream) subscribe() (<-chan StreamEvent, func()) {
	s.mu.Lock()
	bufferSize := len(s.events) + streamSubscriberBuffer
	if bufferSize < 1 {
		bufferSize = 1
	}
	events := make(chan StreamEvent, bufferSize)
	for _, event := range s.events {
		events <- event
	}
	if s.done {
		close(events)
		s.mu.Unlock()
		return events, func() {}
	}
	s.subscribers[events] = struct{}{}
	s.mu.Unlock()

	var once sync.Once
	unsubscribe := func() {
		once.Do(func() {
			s.mu.Lock()
			if _, ok := s.subscribers[events]; ok {
				delete(s.subscribers, events)
				close(events)
			}
			s.mu.Unlock()
		})
	}

	return events, unsubscribe
}

func (s *activeStream) publish(event StreamEvent) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.done {
		return
	}

	s.events = append(s.events, event)
	for subscriber := range s.subscribers {
		select {
		case subscriber <- event:
		default:
			delete(s.subscribers, subscriber)
			close(subscriber)
		}
	}
}

func (s *activeStream) complete() {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.done {
		return
	}
	s.done = true
	for subscriber := range s.subscribers {
		close(subscriber)
		delete(s.subscribers, subscriber)
	}
}
