import { render } from "ink";

process.env.NEXT_PUBLIC_API_BASE_URL ??=
	process.env.AIA_API_BASE_URL ?? "http://127.0.0.1:3000";

void import("./app").then(({ ChatCliApp }) => {
	render(<ChatCliApp apiBase={process.env.NEXT_PUBLIC_API_BASE_URL} />);
});
