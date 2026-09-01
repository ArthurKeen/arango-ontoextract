import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CreateOntologyDialog from "../CreateOntologyDialog";

jest.mock("@/lib/api-client", () => ({
  api: {
    get: jest.fn().mockResolvedValue({
      data: [
        { _key: "ont1", name: "Ontology One" },
        { _key: "ont2", name: "Ontology Two" },
      ],
      cursor: null,
      has_more: false,
      total_count: 2,
    }),
    post: jest.fn().mockResolvedValue({
      ontology_id: "new_ont",
      name: "My Ontology",
      imports_created: [],
      warnings: [],
    }),
    put: jest.fn().mockResolvedValue({}),
  },
}));

// Handle to the mocked PUT, for the competency-question tests below.
const { api: mockedApi } = require("@/lib/api-client") as {
  api: { put: jest.Mock };
};
const apiPut = mockedApi.put;

jest.mock("@/lib/auth", () => ({
  getToken: jest.fn().mockReturnValue(null),
}));

describe("CreateOntologyDialog", () => {
  const mockClose = jest.fn();
  const mockCreated = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("gives every form control its own text colour", () => {
    // The dialog is white in both themes. Its labels declare a colour but its
    // inputs did not, so in dark mode they inherited white from the document
    // and the Tier value was invisible on the white panel. The subtree-level
    // fix is in globals.css; this pins the controls so a future edit cannot
    // quietly go back to relying on inheritance.
    render(
      <CreateOntologyDialog
        open={true}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );

    for (const id of ["ont-name", "ont-desc", "ont-tier"]) {
      const el = document.getElementById(id);
      expect(el).not.toBeNull();
      expect(el!.className).toMatch(
        /\btext-(gray|slate|zinc|neutral)-(8|9)00\b/,
      );
    }
  });

  it("renders nothing when closed", () => {
    const { container } = render(
      <CreateOntologyDialog
        open={false}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the dialog when open", async () => {
    render(
      <CreateOntologyDialog
        open={true}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );
    expect(screen.getByText("Create New Ontology")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Financial Services/),
    ).toBeInTheDocument();
  });

  it("disables create button when name is empty", () => {
    render(
      <CreateOntologyDialog
        open={true}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );
    const btn = screen.getByRole("button", { name: /Create Ontology/i });
    expect(btn).toBeDisabled();
  });

  it("enables create button after entering a name", () => {
    render(
      <CreateOntologyDialog
        open={true}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );
    const input = screen.getByPlaceholderText(/Financial Services/);
    fireEvent.change(input, { target: { value: "My Ontology" } });
    const btn = screen.getByRole("button", { name: /Create Ontology/i });
    expect(btn).not.toBeDisabled();
  });

  it("calls API and onCreated on submit", async () => {
    const { api } = require("@/lib/api-client");
    render(
      <CreateOntologyDialog
        open={true}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );
    const input = screen.getByPlaceholderText(/Financial Services/);
    fireEvent.change(input, { target: { value: "My Ontology" } });
    fireEvent.click(screen.getByRole("button", { name: /Create Ontology/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/ontology/create",
        expect.objectContaining({
          name: "My Ontology",
        }),
      );
    });

    await waitFor(() => {
      expect(mockCreated).toHaveBeenCalledWith("new_ont");
    });
  });

  it("shows available ontologies as import checkboxes", async () => {
    render(
      <CreateOntologyDialog
        open={true}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Ontology One")).toBeInTheDocument();
      expect(screen.getByText("Ontology Two")).toBeInTheDocument();
    });
  });

  it("calls onClose when Cancel is clicked", () => {
    render(
      <CreateOntologyDialog
        open={true}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(mockClose).toHaveBeenCalledTimes(1);
  });
});

describe("competency questions at creation", () => {
  // Authorable here because this is the moment they can still steer the FIRST
  // extraction (FR-19.4 injects their term set into the prompt). Previously
  // they could only be added afterwards, by right-clicking an ontology that
  // had usually already been extracted into.
  const mockClose = jest.fn();
  const mockCreated = jest.fn();

  beforeEach(() => jest.clearAllMocks());

  function open() {
    render(
      <CreateOntologyDialog
        open={true}
        onClose={mockClose}
        onCreated={mockCreated}
      />,
    );
  }

  it("saves the questions against the new ontology", async () => {
    open();
    fireEvent.change(screen.getByPlaceholderText(/Financial Services/), {
      target: { value: "Tyres" },
    });
    fireEvent.change(screen.getByTestId("cq-input-0"), {
      target: { value: "Which tyres are due for replacement?" },
    });
    fireEvent.click(screen.getByTestId("cq-add"));
    fireEvent.change(screen.getByTestId("cq-input-1"), {
      target: { value: "What is the speed rating of a tyre?" },
    });
    fireEvent.click(screen.getByText("Create Ontology"));

    await waitFor(() => expect(apiPut).toHaveBeenCalled());
    const [url, body] = apiPut.mock.calls.at(-1)!;
    expect(url).toContain("/requirements");
    const cqs = body.use_cases[0].competency_questions.map(
      (q: { text: string }) => q.text,
    );
    expect(cqs).toEqual([
      "Which tyres are due for replacement?",
      "What is the speed rating of a tyre?",
    ]);
  });

  it("does not call the requirements API when none were entered", async () => {
    open();
    fireEvent.change(screen.getByPlaceholderText(/Financial Services/), {
      target: { value: "Empty" },
    });
    fireEvent.click(screen.getByText("Create Ontology"));

    await waitFor(() => expect(mockCreated).toHaveBeenCalled());
    expect(apiPut).not.toHaveBeenCalled();
  });

  it("ignores blank rows rather than saving empty questions", async () => {
    open();
    fireEvent.change(screen.getByPlaceholderText(/Financial Services/), {
      target: { value: "Tyres" },
    });
    fireEvent.change(screen.getByTestId("cq-input-0"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByText("Create Ontology"));

    await waitFor(() => expect(mockCreated).toHaveBeenCalled());
    expect(apiPut).not.toHaveBeenCalled();
  });

  it("still reports the ontology as created when saving questions fails", async () => {
    // The ontology exists by then. A failure to attach questions must not read
    // as "create failed", or the user retries and makes a second ontology.
    apiPut.mockRejectedValueOnce(new Error("boom"));
    open();
    fireEvent.change(screen.getByPlaceholderText(/Financial Services/), {
      target: { value: "Tyres" },
    });
    fireEvent.change(screen.getByTestId("cq-input-0"), {
      target: { value: "Which tyres are due?" },
    });
    fireEvent.click(screen.getByText("Create Ontology"));

    await waitFor(() => expect(mockCreated).toHaveBeenCalled());
    expect(mockClose).toHaveBeenCalled();
  });
});
