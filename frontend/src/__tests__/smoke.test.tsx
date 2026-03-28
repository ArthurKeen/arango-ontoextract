import { render, screen } from "@testing-library/react";
import Home from "@/app/page";

describe("Home page", () => {
  it("renders the application heading", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { name: /arango-ontoextract/i }),
    ).toBeInTheDocument();
  });

  it("renders the tagline", () => {
    render(<Home />);
    expect(
      screen.getByText(/ontology extraction and curation platform/i),
    ).toBeInTheDocument();
  });
});
