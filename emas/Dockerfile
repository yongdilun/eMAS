FROM golang:1.25-bookworm AS build
WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /out/emas ./cmd/emas \
    && CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /out/seed ./cmd/seed

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata wget
COPY --from=build /out/emas /usr/local/bin/emas
COPY --from=build /out/seed /usr/local/bin/seed
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/emas"]
