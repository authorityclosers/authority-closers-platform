#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <queue>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace {

constexpr double kMinutesPerDay = 1440.0;
constexpr double kWorkdayStartMinutes = 9.0 * 60.0;

struct Scenario {
    std::string id;
    int tenants{};
    int learners_per_tenant{};
    int enrollment_days{};
    int course_days{};
    int activities{};
    double activation_probability{};
    double activity_continuation_probability{};
    double human_review_fraction{};
    double intervention_probability{};
    double review_minutes_mean{};
    double review_minutes_sigma{};
    double intervention_minutes_mean{};
    int coaches{};
    double coach_hours_per_day{};
    int workdays_per_week{};
    double sla_hours{};
    int telemetry_events_per_activity{};
    int runs{};
    std::uint64_t seed{};
};

enum class JobKind { Review, Intervention };

struct Job {
    double arrival_minutes{};
    double service_minutes{};
    int tenant{};
    JobKind kind{};
};

struct RunResult {
    int activated{};
    int completed{};
    int review_jobs{};
    int intervention_jobs{};
    double service_minutes{};
    int max_waiting_jobs{};
    int peak_jobs_per_day{};
    int peak_telemetry_events_per_day{};
    std::vector<double> turnaround_hours;
    std::vector<std::vector<double>> tenant_turnaround_hours;
};

struct AggregateResult {
    Scenario scenario;
    double mean_activated{};
    double mean_completed{};
    double completion_rate_pct{};
    double mean_review_jobs{};
    double mean_intervention_jobs{};
    double mean_total_jobs{};
    double mean_demand_capacity_pct{};
    double p50_turnaround_hours{};
    double p95_turnaround_hours{};
    double sla_met_pct{};
    double within_48h_pct{};
    double within_72h_pct{};
    double mean_max_waiting_jobs{};
    double mean_peak_jobs_per_day{};
    double mean_peak_telemetry_events_per_day{};
    double worst_tenant_p95_turnaround_hours{};
};

std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, ',')) {
        fields.push_back(field);
    }
    if (!line.empty() && line.back() == ',') {
        fields.emplace_back();
    }
    return fields;
}

double parse_double(const std::string& value, const std::string& field) {
    std::size_t consumed = 0;
    const double parsed = std::stod(value, &consumed);
    if (consumed != value.size()) {
        throw std::runtime_error("invalid numeric value for " + field + ": " + value);
    }
    return parsed;
}

int parse_int(const std::string& value, const std::string& field) {
    std::size_t consumed = 0;
    const long parsed = std::stol(value, &consumed);
    if (consumed != value.size() || parsed < std::numeric_limits<int>::min() ||
        parsed > std::numeric_limits<int>::max()) {
        throw std::runtime_error("invalid integer value for " + field + ": " + value);
    }
    return static_cast<int>(parsed);
}

std::uint64_t parse_uint64(const std::string& value, const std::string& field) {
    std::size_t consumed = 0;
    const unsigned long long parsed = std::stoull(value, &consumed);
    if (consumed != value.size()) {
        throw std::runtime_error("invalid integer value for " + field + ": " + value);
    }
    return static_cast<std::uint64_t>(parsed);
}

void validate_scenario(const Scenario& scenario) {
    const auto probability = [&](double value, const std::string& name) {
        if (value < 0.0 || value > 1.0) {
            throw std::runtime_error(scenario.id + ": " + name + " must be between 0 and 1");
        }
    };
    if (scenario.id.empty()) {
        throw std::runtime_error("scenario_id must not be blank");
    }
    if (scenario.tenants <= 0 || scenario.learners_per_tenant <= 0 ||
        scenario.enrollment_days <= 0 || scenario.course_days <= 0 || scenario.activities <= 0 ||
        scenario.coaches <= 0 || scenario.runs <= 0) {
        throw std::runtime_error(scenario.id + ": count and duration fields must be positive");
    }
    if (scenario.workdays_per_week <= 0 || scenario.workdays_per_week > 7) {
        throw std::runtime_error(scenario.id + ": workdays_per_week must be in [1, 7]");
    }
    if (scenario.coach_hours_per_day <= 0.0 || scenario.coach_hours_per_day > 15.0 ||
        scenario.review_minutes_mean <= 0.0 || scenario.review_minutes_sigma < 0.0 ||
        scenario.intervention_minutes_mean <= 0.0 || scenario.sla_hours <= 0.0 ||
        scenario.telemetry_events_per_activity < 0) {
        throw std::runtime_error(scenario.id + ": workload fields are outside supported bounds");
    }
    probability(scenario.activation_probability, "activation_probability");
    probability(scenario.activity_continuation_probability,
                "activity_continuation_probability");
    probability(scenario.human_review_fraction, "human_review_fraction");
    probability(scenario.intervention_probability, "intervention_probability");
}

std::vector<Scenario> read_scenarios(const std::string& path) {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("unable to open scenario file: " + path);
    }

    std::string header;
    if (!std::getline(input, header)) {
        throw std::runtime_error("scenario file is empty: " + path);
    }
    const std::vector<std::string> expected_header = {
        "scenario_id",
        "tenants",
        "learners_per_tenant",
        "enrollment_days",
        "course_days",
        "activities",
        "activation_probability",
        "activity_continuation_probability",
        "human_review_fraction",
        "intervention_probability",
        "review_minutes_mean",
        "review_minutes_sigma",
        "intervention_minutes_mean",
        "coaches",
        "coach_hours_per_day",
        "workdays_per_week",
        "sla_hours",
        "telemetry_events_per_activity",
        "runs",
        "seed",
    };
    if (split_csv_line(header) != expected_header) {
        throw std::runtime_error("scenario CSV header does not match the simulator contract");
    }

    std::vector<Scenario> scenarios;
    std::string line;
    int line_number = 1;
    while (std::getline(input, line)) {
        ++line_number;
        if (line.empty() || line.front() == '#') {
            continue;
        }
        const auto fields = split_csv_line(line);
        if (fields.size() != expected_header.size()) {
            throw std::runtime_error("scenario CSV line " + std::to_string(line_number) +
                                     " has " + std::to_string(fields.size()) +
                                     " fields; expected " +
                                     std::to_string(expected_header.size()));
        }
        Scenario scenario{
            fields[0],
            parse_int(fields[1], expected_header[1]),
            parse_int(fields[2], expected_header[2]),
            parse_int(fields[3], expected_header[3]),
            parse_int(fields[4], expected_header[4]),
            parse_int(fields[5], expected_header[5]),
            parse_double(fields[6], expected_header[6]),
            parse_double(fields[7], expected_header[7]),
            parse_double(fields[8], expected_header[8]),
            parse_double(fields[9], expected_header[9]),
            parse_double(fields[10], expected_header[10]),
            parse_double(fields[11], expected_header[11]),
            parse_double(fields[12], expected_header[12]),
            parse_int(fields[13], expected_header[13]),
            parse_double(fields[14], expected_header[14]),
            parse_int(fields[15], expected_header[15]),
            parse_double(fields[16], expected_header[16]),
            parse_int(fields[17], expected_header[17]),
            parse_int(fields[18], expected_header[18]),
            parse_uint64(fields[19], expected_header[19]),
        };
        validate_scenario(scenario);
        scenarios.push_back(std::move(scenario));
    }
    if (scenarios.empty()) {
        throw std::runtime_error("scenario file contains no scenarios: " + path);
    }
    return scenarios;
}

bool is_workday(int day, int workdays_per_week) {
    const int weekday = ((day % 7) + 7) % 7;
    return weekday < workdays_per_week;
}

double normalize_to_work_time(double time_minutes, int workdays_per_week,
                              double coach_hours_per_day) {
    int day = static_cast<int>(std::floor(time_minutes / kMinutesPerDay));
    double minute_of_day = time_minutes - static_cast<double>(day) * kMinutesPerDay;
    const double workday_end = kWorkdayStartMinutes + coach_hours_per_day * 60.0;
    while (true) {
        if (!is_workday(day, workdays_per_week)) {
            ++day;
            minute_of_day = 0.0;
            continue;
        }
        if (minute_of_day < kWorkdayStartMinutes) {
            return static_cast<double>(day) * kMinutesPerDay + kWorkdayStartMinutes;
        }
        if (minute_of_day < workday_end) {
            return static_cast<double>(day) * kMinutesPerDay + minute_of_day;
        }
        ++day;
        minute_of_day = 0.0;
    }
}

double add_work_minutes(double start_minutes, double service_minutes, int workdays_per_week,
                        double coach_hours_per_day) {
    double cursor = normalize_to_work_time(start_minutes, workdays_per_week, coach_hours_per_day);
    double remaining = service_minutes;
    const double workday_end = kWorkdayStartMinutes + coach_hours_per_day * 60.0;
    while (remaining > 1e-9) {
        const int day = static_cast<int>(std::floor(cursor / kMinutesPerDay));
        const double minute_of_day = cursor - static_cast<double>(day) * kMinutesPerDay;
        const double available = workday_end - minute_of_day;
        if (remaining <= available + 1e-9) {
            return cursor + remaining;
        }
        remaining -= std::max(0.0, available);
        cursor = normalize_to_work_time(static_cast<double>(day + 1) * kMinutesPerDay,
                                        workdays_per_week, coach_hours_per_day);
    }
    return cursor;
}

double percentile(std::vector<double> values, double p) {
    if (values.empty()) {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    const double position = p * static_cast<double>(values.size() - 1);
    const auto lower = static_cast<std::size_t>(std::floor(position));
    const auto upper = static_cast<std::size_t>(std::ceil(position));
    const double weight = position - static_cast<double>(lower);
    return values[lower] * (1.0 - weight) + values[upper] * weight;
}

double sample_lognormal_with_mean(std::mt19937_64& random, double mean, double sigma) {
    if (sigma == 0.0) {
        return mean;
    }
    const double mu = std::log(mean) - 0.5 * sigma * sigma;
    return std::lognormal_distribution<double>(mu, sigma)(random);
}

int count_workdays(int total_days, int workdays_per_week) {
    int result = 0;
    for (int day = 0; day < total_days; ++day) {
        if (is_workday(day, workdays_per_week)) {
            ++result;
        }
    }
    return result;
}

RunResult simulate_once(const Scenario& scenario, std::uint64_t seed) {
    std::mt19937_64 random(seed);
    std::bernoulli_distribution activates(scenario.activation_probability);
    std::bernoulli_distribution continues(scenario.activity_continuation_probability);
    std::bernoulli_distribution needs_review(scenario.human_review_fraction);
    std::bernoulli_distribution needs_intervention(scenario.intervention_probability);
    std::uniform_real_distribution<double> enrollment_time(
        0.0, static_cast<double>(scenario.enrollment_days) * kMinutesPerDay);
    std::exponential_distribution<double> activation_delay(1.0 / (1.5 * kMinutesPerDay));
    std::uniform_real_distribution<double> cadence_jitter(0.70, 1.30);

    RunResult result;
    result.tenant_turnaround_hours.resize(static_cast<std::size_t>(scenario.tenants));
    std::vector<Job> jobs;
    std::map<int, int> telemetry_by_day;
    const double cadence_minutes =
        static_cast<double>(scenario.course_days) * kMinutesPerDay / scenario.activities;

    for (int tenant = 0; tenant < scenario.tenants; ++tenant) {
        for (int learner = 0; learner < scenario.learners_per_tenant; ++learner) {
            const double enrolled_at = enrollment_time(random);
            if (!activates(random)) {
                continue;
            }
            ++result.activated;
            const double activated_at =
                enrolled_at + std::min(activation_delay(random), 7.0 * kMinutesPerDay);
            int completed_activities = 0;
            double last_activity_at = activated_at;
            for (int activity = 0; activity < scenario.activities; ++activity) {
                if (activity > 0 && !continues(random)) {
                    break;
                }
                const double scheduled_activity_at =
                    activated_at + static_cast<double>(activity + 1) * cadence_minutes *
                                       cadence_jitter(random);
                last_activity_at = std::max(last_activity_at + 30.0, scheduled_activity_at);
                ++completed_activities;
                telemetry_by_day[static_cast<int>(last_activity_at / kMinutesPerDay)] +=
                    scenario.telemetry_events_per_activity;
                if (needs_review(random)) {
                    jobs.push_back(Job{
                        last_activity_at,
                        sample_lognormal_with_mean(random, scenario.review_minutes_mean,
                                                   scenario.review_minutes_sigma),
                        tenant,
                        JobKind::Review,
                    });
                    ++result.review_jobs;
                }
            }
            if (completed_activities == scenario.activities) {
                ++result.completed;
            } else if (needs_intervention(random)) {
                jobs.push_back(Job{
                    last_activity_at + 3.0 * kMinutesPerDay,
                    scenario.intervention_minutes_mean,
                    tenant,
                    JobKind::Intervention,
                });
                ++result.intervention_jobs;
            }
        }
    }

    std::sort(jobs.begin(), jobs.end(), [](const Job& left, const Job& right) {
        return std::tie(left.arrival_minutes, left.tenant) <
               std::tie(right.arrival_minutes, right.tenant);
    });

    std::vector<double> coach_available(static_cast<std::size_t>(scenario.coaches),
                                        kWorkdayStartMinutes);
    std::vector<std::pair<double, int>> waiting_events;
    std::map<int, int> jobs_by_day;
    for (const auto& job : jobs) {
        std::size_t selected = 0;
        double selected_start = std::numeric_limits<double>::infinity();
        for (std::size_t coach = 0; coach < coach_available.size(); ++coach) {
            const double candidate = normalize_to_work_time(
                std::max(job.arrival_minutes, coach_available[coach]),
                scenario.workdays_per_week, scenario.coach_hours_per_day);
            if (candidate < selected_start) {
                selected = coach;
                selected_start = candidate;
            }
        }
        const double completed_at = add_work_minutes(
            selected_start, job.service_minutes, scenario.workdays_per_week,
            scenario.coach_hours_per_day);
        coach_available[selected] = completed_at;
        result.service_minutes += job.service_minutes;
        const double turnaround_hours = (completed_at - job.arrival_minutes) / 60.0;
        result.turnaround_hours.push_back(turnaround_hours);
        result.tenant_turnaround_hours[static_cast<std::size_t>(job.tenant)].push_back(
            turnaround_hours);
        jobs_by_day[static_cast<int>(job.arrival_minutes / kMinutesPerDay)] += 1;
        if (selected_start > job.arrival_minutes + 1e-9) {
            waiting_events.emplace_back(job.arrival_minutes, 1);
            waiting_events.emplace_back(selected_start, -1);
        }
    }

    std::sort(waiting_events.begin(), waiting_events.end(),
              [](const auto& left, const auto& right) {
                  if (left.first != right.first) {
                      return left.first < right.first;
                  }
                  return left.second > right.second;
              });
    int waiting = 0;
    for (const auto& [time, delta] : waiting_events) {
        static_cast<void>(time);
        waiting += delta;
        result.max_waiting_jobs = std::max(result.max_waiting_jobs, waiting);
    }
    for (const auto& [day, count] : jobs_by_day) {
        static_cast<void>(day);
        result.peak_jobs_per_day = std::max(result.peak_jobs_per_day, count);
    }
    for (const auto& [day, count] : telemetry_by_day) {
        static_cast<void>(day);
        result.peak_telemetry_events_per_day =
            std::max(result.peak_telemetry_events_per_day, count);
    }
    return result;
}

AggregateResult aggregate(const Scenario& scenario) {
    AggregateResult aggregate_result;
    aggregate_result.scenario = scenario;
    std::vector<double> all_turnaround;
    std::vector<std::vector<double>> tenant_turnaround(
        static_cast<std::size_t>(scenario.tenants));
    double sla_met = 0.0;
    double within_48h = 0.0;
    double within_72h = 0.0;
    double total_jobs = 0.0;
    const int total_learners = scenario.tenants * scenario.learners_per_tenant;
    const int capacity_days = scenario.enrollment_days + scenario.course_days;
    const double available_minutes =
        static_cast<double>(count_workdays(capacity_days, scenario.workdays_per_week)) *
        scenario.coach_hours_per_day * 60.0 * scenario.coaches;

    for (int run = 0; run < scenario.runs; ++run) {
        const std::uint64_t run_seed = scenario.seed +
                                       static_cast<std::uint64_t>(run) *
                                           0x9E3779B97F4A7C15ULL;
        RunResult current = simulate_once(scenario, run_seed);
        aggregate_result.mean_activated += current.activated;
        aggregate_result.mean_completed += current.completed;
        aggregate_result.mean_review_jobs += current.review_jobs;
        aggregate_result.mean_intervention_jobs += current.intervention_jobs;
        aggregate_result.mean_demand_capacity_pct +=
            available_minutes > 0.0 ? current.service_minutes / available_minutes * 100.0 : 0.0;
        aggregate_result.mean_max_waiting_jobs += current.max_waiting_jobs;
        aggregate_result.mean_peak_jobs_per_day += current.peak_jobs_per_day;
        aggregate_result.mean_peak_telemetry_events_per_day +=
            current.peak_telemetry_events_per_day;
        for (double turnaround : current.turnaround_hours) {
            all_turnaround.push_back(turnaround);
            sla_met += turnaround <= scenario.sla_hours ? 1.0 : 0.0;
            within_48h += turnaround <= 48.0 ? 1.0 : 0.0;
            within_72h += turnaround <= 72.0 ? 1.0 : 0.0;
            total_jobs += 1.0;
        }
        for (std::size_t tenant = 0; tenant < tenant_turnaround.size(); ++tenant) {
            tenant_turnaround[tenant].insert(tenant_turnaround[tenant].end(),
                                             current.tenant_turnaround_hours[tenant].begin(),
                                             current.tenant_turnaround_hours[tenant].end());
        }
    }

    const double divisor = static_cast<double>(scenario.runs);
    aggregate_result.mean_activated /= divisor;
    aggregate_result.mean_completed /= divisor;
    aggregate_result.mean_review_jobs /= divisor;
    aggregate_result.mean_intervention_jobs /= divisor;
    aggregate_result.mean_total_jobs =
        aggregate_result.mean_review_jobs + aggregate_result.mean_intervention_jobs;
    aggregate_result.mean_demand_capacity_pct /= divisor;
    aggregate_result.mean_max_waiting_jobs /= divisor;
    aggregate_result.mean_peak_jobs_per_day /= divisor;
    aggregate_result.mean_peak_telemetry_events_per_day /= divisor;
    aggregate_result.completion_rate_pct =
        aggregate_result.mean_completed / static_cast<double>(total_learners) * 100.0;
    aggregate_result.p50_turnaround_hours = percentile(all_turnaround, 0.50);
    aggregate_result.p95_turnaround_hours = percentile(all_turnaround, 0.95);
    aggregate_result.sla_met_pct = total_jobs > 0.0 ? sla_met / total_jobs * 100.0 : 100.0;
    aggregate_result.within_48h_pct =
        total_jobs > 0.0 ? within_48h / total_jobs * 100.0 : 100.0;
    aggregate_result.within_72h_pct =
        total_jobs > 0.0 ? within_72h / total_jobs * 100.0 : 100.0;
    for (auto& values : tenant_turnaround) {
        aggregate_result.worst_tenant_p95_turnaround_hours =
            std::max(aggregate_result.worst_tenant_p95_turnaround_hours,
                     percentile(values, 0.95));
    }
    return aggregate_result;
}

void write_csv(const std::string& path, const std::vector<AggregateResult>& results) {
    std::ofstream output(path);
    if (!output) {
        throw std::runtime_error("unable to write CSV output: " + path);
    }
    output << "scenario_id,tenants,total_learners,coaches,simulations,mean_activated,"
              "mean_completed,completion_rate_pct,mean_review_jobs,mean_intervention_jobs,"
              "mean_total_jobs,mean_demand_capacity_pct,p50_turnaround_hours,"
              "p95_turnaround_hours,target_sla_hours,target_sla_met_pct,within_48h_pct,"
              "within_72h_pct,mean_max_waiting_jobs,"
              "mean_peak_jobs_per_day,mean_peak_telemetry_events_per_day,"
              "worst_tenant_p95_turnaround_hours\n";
    output << std::fixed << std::setprecision(2);
    for (const auto& result : results) {
        const int total_learners =
            result.scenario.tenants * result.scenario.learners_per_tenant;
        output << result.scenario.id << ',' << result.scenario.tenants << ',' << total_learners
               << ',' << result.scenario.coaches << ',' << result.scenario.runs << ','
               << result.mean_activated << ',' << result.mean_completed << ','
               << result.completion_rate_pct << ',' << result.mean_review_jobs << ','
               << result.mean_intervention_jobs << ',' << result.mean_total_jobs << ','
               << result.mean_demand_capacity_pct << ',' << result.p50_turnaround_hours << ','
               << result.p95_turnaround_hours << ',' << result.scenario.sla_hours << ','
               << result.sla_met_pct << ',' << result.within_48h_pct << ','
               << result.within_72h_pct << ','
               << result.mean_max_waiting_jobs << ',' << result.mean_peak_jobs_per_day << ','
               << result.mean_peak_telemetry_events_per_day << ','
               << result.worst_tenant_p95_turnaround_hours << '\n';
    }
}

void write_markdown(const std::string& path, const std::vector<AggregateResult>& results) {
    std::ofstream output(path);
    if (!output) {
        throw std::runtime_error("unable to write Markdown output: " + path);
    }
    output << "# Academy capacity simulation results\n\n"
              "Generated by `academy_capacity_sim.cpp`. These are scenario-model outputs, not "
              "observed learner outcomes or staffing commitments.\n\n"
              "| Scenario | Tenants | Learners | Coaches | Runs | Completion | Mean jobs | "
              "Demand / planned capacity | P50 turnaround | P95 turnaround | Within 24h | "
              "Within 48h | Mean max waiting | Peak jobs/day | Peak telemetry/day | "
              "Worst tenant P95 |\n"
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
              "---: | ---: | ---: | ---: | ---: | ---: |\n";
    output << std::fixed << std::setprecision(1);
    for (const auto& result : results) {
        const int total_learners =
            result.scenario.tenants * result.scenario.learners_per_tenant;
        output << "| " << result.scenario.id << " | " << result.scenario.tenants << " | "
               << total_learners << " | " << result.scenario.coaches << " | "
               << result.scenario.runs << " | " << result.completion_rate_pct << "% | "
               << result.mean_total_jobs << " | " << result.mean_demand_capacity_pct << "% | "
               << result.p50_turnaround_hours << " h | " << result.p95_turnaround_hours
               << " h | " << result.sla_met_pct << "% | " << result.within_48h_pct
               << "% | "
               << result.mean_max_waiting_jobs << " | " << result.mean_peak_jobs_per_day
               << " | " << result.mean_peak_telemetry_events_per_day << " | "
               << result.worst_tenant_p95_turnaround_hours << " h |\n";
    }
    output << "\n## Interpretation guardrails\n\n"
              "- Completion is generated from declared activation and per-activity continuation "
              "probabilities; it is not a forecast.\n"
              "- The queue represents human review and bounded re-engagement work only. It does "
              "not model official automated scoring.\n"
              "- Demand/capacity uses the configured coaching hours within the enrollment plus "
              "course window. Turnaround includes nights and non-working days.\n"
              "- Telemetry volume is an engineering load estimate. Telemetry never becomes "
              "canonical progress, entitlement, payment, or assessment state.\n";
}

double erlang_c_wait_hours(double arrivals_per_hour, double service_per_hour, int servers) {
    const double offered_load = arrivals_per_hour / service_per_hour;
    const double utilization = offered_load / static_cast<double>(servers);
    if (utilization >= 1.0) {
        return std::numeric_limits<double>::infinity();
    }
    double sum = 0.0;
    double term = 1.0;
    for (int n = 0; n < servers; ++n) {
        if (n > 0) {
            term *= offered_load / static_cast<double>(n);
        }
        sum += term;
    }
    term *= offered_load / static_cast<double>(servers);
    const double tail = term / (1.0 - utilization);
    const double probability_wait = tail / (sum + tail);
    return probability_wait /
           (static_cast<double>(servers) * service_per_hour - arrivals_per_hour);
}

double simulate_mmc_wait_hours(std::uint64_t seed, double arrivals_per_hour,
                               double service_per_hour, int servers, int samples,
                               int burn_in) {
    std::mt19937_64 random(seed);
    std::exponential_distribution<double> interarrival(arrivals_per_hour);
    std::exponential_distribution<double> service(service_per_hour);
    std::priority_queue<double, std::vector<double>, std::greater<>> available;
    for (int server = 0; server < servers; ++server) {
        available.push(0.0);
    }
    double arrival = 0.0;
    double total_wait = 0.0;
    int observed = 0;
    for (int sample = 0; sample < samples + burn_in; ++sample) {
        arrival += interarrival(random);
        const double earliest = available.top();
        available.pop();
        const double start = std::max(arrival, earliest);
        if (sample >= burn_in) {
            total_wait += start - arrival;
            ++observed;
        }
        available.push(start + service(random));
    }
    return total_wait / static_cast<double>(observed);
}

void require_test(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error("self-test failed: " + message);
    }
}

void run_self_tests() {
    const double saturday_late = 5.0 * kMinutesPerDay + 16.5 * 60.0;
    const double finish = add_work_minutes(saturday_late, 120.0, 6, 8.0);
    const double expected_monday = 7.0 * kMinutesPerDay + 10.5 * 60.0;
    require_test(std::abs(finish - expected_monday) < 1e-6,
                 "work calendar must carry service over the non-working day");

    const double theoretical = erlang_c_wait_hours(2.0, 1.0, 3);
    const double simulated = simulate_mmc_wait_hours(20260904ULL, 2.0, 1.0, 3, 400000, 10000);
    require_test(std::abs(simulated - theoretical) / theoretical < 0.06,
                 "M/M/c simulated mean wait must be within 6% of Erlang C");

    Scenario deterministic{"determinism", 1, 12, 7, 21, 6, 0.8, 0.9, 0.3, 0.4,
                           12.0,          0.35, 8.0, 1, 2.0, 6, 24.0, 10, 1, 99};
    const auto first = simulate_once(deterministic, deterministic.seed);
    const auto second = simulate_once(deterministic, deterministic.seed);
    require_test(first.activated == second.activated && first.completed == second.completed &&
                     first.review_jobs == second.review_jobs &&
                     first.intervention_jobs == second.intervention_jobs &&
                     first.turnaround_hours == second.turnaround_hours,
                 "a fixed seed must reproduce the same result");

    Scenario zero_jobs{"zero-jobs", 1, 10, 7, 14, 4, 1.0, 1.0, 0.0, 0.0,
                       10.0,        0.2,  5.0, 1, 2.0, 6, 24.0, 5, 1, 10};
    const auto empty = simulate_once(zero_jobs, zero_jobs.seed);
    require_test(empty.review_jobs == 0 && empty.intervention_jobs == 0 &&
                     empty.turnaround_hours.empty(),
                 "zero review and intervention probabilities must create no jobs");

    std::cout << std::fixed << std::setprecision(5)
              << "self-test: PASS\n"
              << "erlang-c theoretical mean wait hours: " << theoretical << "\n"
              << "simulated mean wait hours: " << simulated << "\n";
}

struct Arguments {
    bool self_test{};
    std::string scenarios;
    std::string csv_output;
    std::string markdown_output;
};

Arguments parse_arguments(int argc, char** argv) {
    Arguments arguments;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--self-test") {
            arguments.self_test = true;
        } else if ((argument == "--scenarios" || argument == "--csv" ||
                    argument == "--markdown") &&
                   index + 1 < argc) {
            const std::string value = argv[++index];
            if (argument == "--scenarios") {
                arguments.scenarios = value;
            } else if (argument == "--csv") {
                arguments.csv_output = value;
            } else {
                arguments.markdown_output = value;
            }
        } else {
            throw std::runtime_error("unknown or incomplete argument: " + argument);
        }
    }
    return arguments;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Arguments arguments = parse_arguments(argc, argv);
        if (arguments.self_test) {
            run_self_tests();
            return 0;
        }
        if (arguments.scenarios.empty() || arguments.csv_output.empty() ||
            arguments.markdown_output.empty()) {
            std::cerr << "usage: academy_capacity_sim --scenarios INPUT.csv --csv OUTPUT.csv "
                         "--markdown OUTPUT.md\n"
                      << "       academy_capacity_sim --self-test\n";
            return 2;
        }
        const auto scenarios = read_scenarios(arguments.scenarios);
        std::vector<AggregateResult> results;
        results.reserve(scenarios.size());
        for (const auto& scenario : scenarios) {
            std::cout << "simulating " << scenario.id << " (" << scenario.runs << " runs)\n";
            results.push_back(aggregate(scenario));
        }
        write_csv(arguments.csv_output, results);
        write_markdown(arguments.markdown_output, results);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
