# Chat Route Design

## Goal

Update the chat frontend so an empty new chat lives at `/chat`, while existing conversations live at `/chat/{conversationId}`.

## Behavior

- Opening a new chat navigates to `/chat` and does not create a backend conversation.
- Selecting a historical conversation navigates to `/chat/{conversationId}`.
- If the current page is already an unsent empty chat, clicking the new chat button does nothing.
- If the user sends the first message from `/chat`, the frontend creates a backend conversation, switches the active conversation to the new id, replaces the URL with `/chat/{conversationId}`, then starts streaming the assistant response.
- Loading `/chat/{conversationId}` directly selects that conversation and loads its messages.

## Approach

- Add route entries for `/chat` and `/chat/[conversationId]` that render the shared `ChatShell`.
- Let `ChatShell` accept an optional `conversationId` prop and synchronize it into the chat store after conversations load.
- Add store support for clearing the active conversation when viewing `/chat`.
- Use Next navigation in the sidebar instead of only mutating store state.
- Keep conversation creation lazy in `sendMessage` so empty chats are not persisted.

## Edge Cases

- `/chat` with an active persisted conversation should clear the active id and show an empty input state.
- Clicking new chat while already on `/chat` with no active conversation should be a no-op.
- Clicking new chat while viewing `/chat/{conversationId}` should navigate to `/chat`.
- Directly opening an unknown conversation id should not crash; it should surface the existing message loading error behavior if the backend rejects it.

## Verification

- Run the frontend linter.
- Build the frontend if lint passes or if route types need validation.
- Manually verify navigation behavior for `/chat`, `/chat/{conversationId}`, new chat, historical chat selection, and first-message creation.
