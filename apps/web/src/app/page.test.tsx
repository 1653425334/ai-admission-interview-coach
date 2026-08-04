import { render, screen } from "@testing-library/react";
import Home from "./page";

it("renders the product name", () => {
  render(<Home />);
  expect(
    screen.getByRole("heading", { name: "AI Admission Interview Coach" }),
  ).toBeInTheDocument();
});
