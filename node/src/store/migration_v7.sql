-- v6 -> v7. Existing messages acquire no inferred outbound ACK budget.
ALTER TABLE messages ADD COLUMN data_ack_budget TEXT CHECK(length(data_ack_budget)<=1024);
ALTER TABLE control_output_rate ADD COLUMN exit_cursor TEXT CHECK(length(exit_cursor)<=512);
ALTER TABLE control_output_rate ADD COLUMN ordinary_cursor TEXT CHECK(length(ordinary_cursor)<=512);
PRAGMA user_version = 7;
