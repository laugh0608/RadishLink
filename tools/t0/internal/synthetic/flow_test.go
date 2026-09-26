package synthetic

import (
	"bytes"
	"testing"
)

type pendingInput struct {
	at     int64
	target string
	input  Input
}
type world struct {
	nodes    map[string]*Node
	oracles  map[string]testOracle
	pending  []pendingInput
	dropped  bool
	maxBytes int
}

func newWorld(t *testing.T) *world {
	t.Helper()
	w := &world{nodes: map[string]*Node{}, oracles: map[string]testOracle{}}
	for _, name := range []string{"A", "B", "C"} {
		w.nodes[name], w.oracles[name] = testNode(t, name)
	}
	return w
}
func (w *world) run(t *testing.T, size int, fault string) {
	t.Helper()
	mustSubmit(t, w.nodes["A"], "one", testID, size)
	var current int64
	for step := 0; step < 500; step++ {
		next := int64(100001)
		for _, p := range w.pending {
			if p.at > current {
				next = min(next, p.at)
			}
		}
		for _, n := range w.nodes {
			for _, q := range n.storage.current.Queues {
				if q.Status != "active" {
					continue
				}
				for _, off := range []int64{0, 250, 750, 1750, 3750} {
					at := q.Start + off
					if at == 0 {
						at = 1
					}
					if at > current {
						next = min(next, at)
					}
				}
			}
		}
		if fault == "down-ab" && !w.dropped {
			next = min(next, int64(5000))
		}
		if fault == "down-bc" && !w.dropped {
			next = min(next, int64(5300))
		}
		if next > 10000 {
			return
		}
		if next <= current {
			t.Fatal("test schedule did not advance")
		}
		current = next
		for _, name := range []string{"A", "B", "C"} {
			n := w.nodes[name]
			batch := Batch{Now: current}
			remaining := []pendingInput{}
			for _, p := range w.pending {
				if p.at == current && p.target == name {
					batch.Inputs = append(batch.Inputs, p.input)
				} else {
					remaining = append(remaining, p)
				}
			}
			w.pending = remaining
			due := len(batch.Inputs) > 0
			for _, q := range n.storage.current.Queues {
				if q.Status == "active" {
					for _, off := range []int64{0, 250, 750, 1750, 3750} {
						at := q.Start + off
						if at == 0 {
							at = 1
						}
						if at == current {
							due = true
						}
					}
				}
			}
			if fault == "down-ab" && name == "A" {
				if current == 1 {
					batch.Links = []Link{{"B", "became_down"}}
					due = true
				}
				if current == 5000 {
					batch.Links = []Link{{"B", "became_up"}}
					due = true
					w.dropped = true
				}
			}
			if fault == "down-bc" && name == "B" {
				if len(batch.Inputs) > 0 && n.storage.current.find(fixtureData(size).Key()) == nil {
					batch.Links = []Link{{"C", "became_down"}}
				}
				if current == 5300 {
					batch.Links = []Link{{"C", "became_up"}}
					due = true
					w.dropped = true
				}
			}
			if !due {
				continue
			}
			out := mustStep(t, n, batch)
			for _, send := range out {
				var stream bytes.Buffer
				if err := send.Write(&stream, current); err != nil {
					t.Fatal(err)
				}
				w.maxBytes = max(w.maxBytes, stream.Len())
				input, err := ReadInput(name, &stream)
				if err != nil {
					t.Fatal(err)
				}
				e, err := DecodeEnvelope(input.Frame)
				if err != nil {
					t.Fatal(err)
				}
				if !w.dropped && e.Kind == "delivery" && (fault == "loss-cb" && name == "C" || fault == "loss-ba" && name == "B") {
					w.dropped = true
					continue
				}
				target := send.Neighbor()
				input = permit(t, w.oracles[target], w.nodes[target], name, e)
				w.pending = append(w.pending, pendingInput{current + 50, target, input})
			}
		}
	}
	t.Fatal("test schedule exceeded bound")
}
func TestPersistentSyntheticFlow(t *testing.T) {
	for _, tc := range []struct {
		name  string
		size  int
		fault string
	}{{"small", 1024, ""}, {"maximum", 16384, ""}, {"loss-cb", 1024, "loss-cb"}, {"loss-ba", 1024, "loss-ba"}, {"down-ab", 1024, "down-ab"}, {"down-bc", 1024, "down-bc"}} {
		t.Run(tc.name, func(t *testing.T) {
			w := newWorld(t)
			w.run(t, tc.size, tc.fault)
			if tc.fault != "" && !w.dropped {
				t.Fatal("fault not hit")
			}
			a, _ := w.nodes["A"].Query("one")
			c, _ := w.nodes["C"].History()
			b := w.nodes["B"].storage.current.Messages
			if a.State != "destination_delivered" || len(c) != 1 || len(c[0].Body) != tc.size || len(b) != 1 || b[0].Body != "" || b[0].State != "destination_delivered" {
				t.Fatalf("incomplete flow: A=%s C=%d B=%v", a.State, len(c), len(b))
			}
			if w.nodes["C"].storage.current.ReceiveSteps != 1 || w.nodes["B"].storage.current.findQueue(b[0].Key, "delivery").Status != "active" {
				t.Fatal("delivery responsibility lost or repeated receive")
			}
			if tc.size == 16384 && w.maxBytes <= 16384 {
				t.Fatal("maximum encoded frame was not sent")
			}
			for _, node := range w.nodes {
				generation := node.Generation()
				reopened, err := OpenNode(node.storage.directory, node.config, Recovery{testEpoch, 10000, generation})
				if err != nil {
					t.Fatal(err)
				}
				if reopened.Generation() != generation {
					t.Fatal("reopen changed state")
				}
				hist, _ := reopened.History()
				old, _ := node.History()
				if len(hist) != len(old) {
					t.Fatal("history changed")
				}
			}
		})
	}
}
